from decimal import Decimal
from types import SimpleNamespace
import pytest
from backoffice.histories import Histories,hand_metrics,replay,winnings

HAND='''***** Hand History for Game 162968912 *****
$1/$2 USD PLO
Seat 1: monica ( $200 USD )
Seat 2: demoOpponent ( $200 USD )
monica posts big blind [$2 USD]
demoOpponent raises [$7 USD]
monica calls [$5 USD]
monica bets [$7 USD]
demoOpponent calls [$7 USD]
monica wins $28 USD
'''


def test_report_counts_only_owned_bots():
    result=winnings(HAND,["monica"])
    assert result=={"monica":{"net":Decimal(14),"hands":1}}
    assert winnings(HAND,["differentBot"])=={}


def test_case_insensitive_names_and_multiple_hands():
    result=winnings(HAND+HAND.replace("162968912","162968913"),["Monica"])
    assert result["Monica"]=={"net":Decimal(28),"hands":2}


def test_incomplete_hand_is_not_a_zero_winnings_result():
    with pytest.raises(ValueError):
        winnings(HAND.replace("monica wins $28 USD", ""),["monica"])


def test_hand_metrics_counts_non_bot_players_and_hero_net():
    result=hand_metrics(HAND,"monica",["monica","kate"])
    assert result=={"human_count":1,"hero_winnings":Decimal(14)}


def test_replay_exposes_known_cards_and_tracks_chips():
    hand=HAND.replace("monica posts big blind [$2 USD]","Dealt to monica [ As Kd ]\nmonica posts big blind [$2 USD]")
    result=replay(hand,"monica")
    assert result["steps"][0]["players"][0]["cards"]==["As","Kd"]
    assert result["steps"][0]["players"][1]["cards"]==[]
    assert result["steps"][-1]["pot"]==Decimal(0)


def test_replay_skips_forced_bets_and_keeps_pot_fixed_within_street():
    hand=HAND.replace("monica posts big blind [$2 USD]", "demoOpponent posts ante [$0.25 USD]\nmonica posts big blind [$2 USD]")
    result=replay(hand,"monica")
    labels=[step["label"] for step in result["steps"]]
    assert labels[0]=="First decision"
    assert not any("posts " in label for label in labels)
    assert result["steps"][0]["players"][0]["bet"]==Decimal(2)
    action_steps=[step for step in result["steps"] if step.get("action_player")]
    assert {step["pot"] for step in action_steps}=={Decimal(0)}


def test_replay_moves_current_bets_into_pot_only_on_new_street():
    hand=HAND.replace("monica bets [$7 USD]", "*** FLOP *** [ As Kd 2c ]\nmonica bets [$7 USD]")
    result=replay(hand,"monica")
    flop=next(i for i,step in enumerate(result["steps"]) if step["label"]=="Flop")
    assert all(step["pot"]==Decimal(0) for step in result["steps"][:flop])
    assert result["steps"][flop]["pot"]==Decimal(14)
    assert all(step["pot"]==Decimal(14) for step in result["steps"][flop:-1])


def test_replay_shows_all_eventually_known_cards_from_start_and_dealer():
    hand=HAND.replace("Total number", "Seat 2 is the button\nTotal number") if "Total number" in HAND else HAND.replace(
        "Seat 1: monica", "Seat 2 is the button\nSeat 1: monica")
    hand=hand.replace("monica posts big blind [$2 USD]", "Dealt to monica [ As Kd ]\nmonica posts big blind [$2 USD]")
    hand=hand.replace("monica wins $28 USD", "demoOpponent shows [ Qh, Qc ]\nmonica wins $28 USD")
    result=replay(hand,"monica")
    first={p["name"]:p for p in result["steps"][0]["players"]}
    assert first["monica"]["cards"]==["As","Kd"]
    assert first["demoOpponent"]["cards"]==["Qh","Qc"]
    assert result["dealer_seat"]==2
    raise_step=next(s for s in result["steps"] if s.get("action_text","").startswith("Raises"))
    assert raise_step["action_player"]=="demoOpponent"
    assert raise_step["action_text"]=="Raises 7"


def test_winnings_report_uses_persisted_results_without_reading_blobs():
    class Database:
        def rows(self, sql, *args):
            if "AccountPolicy" in sql:
                return [{"Username": "monica"}]
            assert "reporting.HandPlayerResult" in sql
            return [{"game_id": 0, "username": "monica", "hands": 1200, "net": Decimal("42.50")}]

        def one(self, sql, *args):
            assert "reporting.HandProcessing" in sql
            return {"total": 1200, "processed": 1200, "failed": 0}

    store = SimpleNamespace(db=Database(), ctx=SimpleNamespace(customer_id=1),
                            site=lambda _site_id: {"timezone": "Europe/Budapest", "name": "Evenbet"})
    histories = Histories(store)
    result = histories.report(1, {"from": "2026-10-01", "to": "2026-10-31"})
    assert result["items"] == [{"game": "NLH", "username": "monica", "hands": 1200,
                                "net": Decimal("42.50")}]
    assert result["processed"] == result["total"] == 1200
    assert result["next_cursor"] is None


STALE_SHOWDOWN = (
    "***** Hand History for Game 9033 *****\r\n"
    "$1.00/$2.00 USD PL Omaha - Saturday, October 31, 00:40:55 CEST 2026\r\n"
    "Seat 1 is the button\r\n"
    "Seat 1: jeremy ( $74.97 USD )\r\n"
    "Seat 6: ScottocS ( $111.26 USD )\r\n"
    "jeremy posts small blind [$1 USD]\r\n"
    "ScottocS posts big blind [$2 USD]\r\n"
    "Dealt to jeremy [  6d 7d 9h 2c ]\r\n"
    "jeremy raises [$4 USD]\r\n"
    "ScottocS calls [$3 USD]\r\n"
    "** Dealing Flop ** [ Th, 8d, 5c ]\r\n"
    "ScottocS bets [$7.13 USD]\r\n"
    "jeremy calls [$7.13 USD]\r\n"
    "** Dealing Turn ** [ 6h ]\r\n"
    "ScottocS bets [$3.6 USD]\r\n"
    "jeremy raises [$34 USD]\r\n"
    "ScottocS raises [$64.36 USD]\r\n"
    "jeremy calls [$28.84 USD]\r\n"
    "** Dealing River ** [ Ac ]\r\n"
    "jeremy does not show cards.\r\n"
    "ScottocS shows [  Qc, Tc, 5d, Kh ]\r\n"
    "ScottocS wins $5.12 USD from the side pot 1\r\n"
    "ScottocS wins $149.94 USD from the main pot\r\n")


def test_stored_files_are_read_with_re_settled_winners():
    # jeremy's hidden 9h 7d make a ten-high straight; the stored file paid ScottocS's pair of tens.
    class Blob:
        def __init__(self, data): self.data = data
        def download_blob(self, **_): return SimpleNamespace(readall=lambda: self.data)

    stored = b"\xef\xbb\xbf" + STALE_SHOWDOWN.encode()
    histories = Histories(SimpleNamespace(db=None))
    histories._container_client = SimpleNamespace(get_blob_client=lambda _path: Blob(stored))
    data = histories._read("14004/Evenbet/9033.txt")
    assert data.startswith(b"\xef\xbb\xbf")
    text = data.decode("utf-8-sig")
    assert "jeremy wins $149.94 USD from the main pot\r\n" in text
    assert "ScottocS wins $5.12 USD from the side pot 1\r\n" in text
    assert "ScottocS wins $149.94" not in text
    assert hand_metrics(text, "jeremy", ["jeremy"])["hero_winnings"] == Decimal("74.97")
