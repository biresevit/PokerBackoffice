import random
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backoffice.distributions import Distributions, assign, pick_for_new, quotas, validate, value_key
from backoffice.validation import Error, parse_csv


def opts(*pairs):
    return [{"value": v, "percent": Decimal(str(p))} for v, p in pairs]


def test_profile_distribution_accepts_choices_totalling_100():
    result = validate("strategy", [{"value": 5, "percent": 15}, {"value": "1", "percent": 85}])
    assert [o["value"] for o in result] == [5, 1]


@pytest.mark.parametrize("options,message", [
    ([{"value": 5, "percent": 15}, {"value": 1, "percent": 80}], "total 100"),
    ([{"value": 5, "percent": 50}, {"value": 5, "percent": 50}], "listed twice"),
    ([{"value": 9, "percent": 100}], "not a valid choice"),
    ([{"value": 5, "percent": 0}, {"value": 1, "percent": 100}], "above 0"),
    ([], "between 1 and"),
])
def test_invalid_profile_distributions_are_refused(options, message):
    with pytest.raises(Error, match=message):
        validate("strategy", options)


def test_chance_values_must_be_between_0_and_1_with_five_decimals():
    assert validate("post_bb_chance", [{"value": "0.33", "percent": 20}, {"value": 0.5, "percent": 80}])[0]["value"] == Decimal("0.33")
    with pytest.raises(Error):
        validate("post_bb_chance", [{"value": 1.2, "percent": 100}])
    with pytest.raises(Error, match="five decimal"):
        validate("post_bb_chance", [{"value": "0.123456", "percent": 100}])


def test_quotas_give_exact_shares_that_add_up():
    options = opts((5, 15), (6, 10), (1, 75))
    assert quotas(500, options) == [75, 50, 375]
    # 7 accounts at 15/10/75 = 1.05/0.7/5.25: the largest remainders get the leftover account
    counts = quotas(7, options)
    assert sum(counts) == 7 and counts == [1, 1, 5]
    assert sum(quotas(1, options)) == 1


def test_assign_gives_every_value_its_exact_share_at_random():
    options = opts(("0.33", 20), ("0.5", 30), ("0.8", 50))
    first = assign(range(500), options, random.Random(1))
    second = assign(range(500), options, random.Random(2))
    for mapping in (first, second):
        values = list(mapping.values())
        assert (values.count("0.33"), values.count("0.5"), values.count("0.8")) == (100, 150, 250)
    assert first != second, "the accounts chosen for each value are random"


def test_new_accounts_fill_the_value_furthest_below_target():
    options = opts(("low", 50), ("medium", 30), ("high", 20))
    counts = {"low": 10, "medium": 0, "high": 0}
    assert pick_for_new(options, counts, random.Random(0)) == "medium"
    # Starting from a lopsided mix, 490 more accounts end exactly on target.
    for _ in range(490):
        value = pick_for_new(options, counts, random.Random(0))
        counts[value] = counts.get(value, 0) + 1
    assert counts == {"low": 250, "medium": 150, "high": 100}


def test_chances_compare_as_numbers():
    assert value_key("post_bb_chance", Decimal("0.50000")) == value_key("post_bb_chance", "0.5")
    assert value_key("strategy", 5) == "5"


class FakeDb:
    def __init__(self, saved, accounts):
        self.saved, self.accounts = saved, accounts

    def rows(self, sql, *args):
        if "AccountDistribution" in sql:
            return self.saved
        return self.accounts


def test_import_picker_counts_profiles_given_in_the_csv():
    saved = [{"field": "strategy", "options": '[{"value": 5, "percent": "50"}, {"value": 1, "percent": "50"}]'}]
    accounts = [{"id": 1, "strategy": 5, "stake": "low", "frequency": "low", "max_minutes": 120, "max_tables": 6,
                 "post_bb_chance": Decimal("0.5"), "run_it_twice_chance": Decimal("0.5"), "rebuy_ring_chance": Decimal("0.5"),
                 "rebuy_tournament_chance": Decimal("0.5"), "show_cards_chance": Decimal("0.5")}]
    store = SimpleNamespace(db=FakeDb(saved, accounts))
    pick = Distributions(store).new_account_picker(1)
    assert pick({"strategy": 1}) == {}          # given in the CSV: counted, not picked
    assert pick({"strategy": None})["strategy"] in (1, 5)
    picks = [pick({"strategy": None})["strategy"] for _ in range(8)]
    # 1 + 1 + 1 picked + 8 = 11 accounts kept as close to 50/50 as possible
    assert abs((picks.count(5) + 1) - (picks.count(1) + 1)) <= 2


def test_csv_profile_column_is_optional():
    none = {"email": None, "password": None}
    assert parse_csv("username\nann\nbob\n") == [{"username": "ann", "strategy": None, **none}, {"username": "bob", "strategy": None, **none}]
    assert parse_csv("username,profile\nann,\nbob,Maniac\n") == [{"username": "ann", "strategy": None, **none}, {"username": "bob", "strategy": 1, **none}]
    with pytest.raises(Error, match="unknown profile"):
        parse_csv("username,profile\nann,Nobody\n")
    with pytest.raises(Error, match="header"):
        parse_csv("username,stake\nann,low\n")


def test_csv_takes_the_login_after_the_username():
    rows = parse_csv("username,password,email\nmatte_99,1MiDkp,matte_99@bots.bluffpoker.invalid\nnick90,,\n")
    assert rows == [{"username": "matte_99", "strategy": None, "email": "matte_99@bots.bluffpoker.invalid", "password": "1MiDkp"},
                    {"username": "nick90", "strategy": None, "email": None, "password": None}]
    assert parse_csv("username,email,password,profile\nann,a@x.io,pw,Maniac\n")[0] == \
        {"username": "ann", "strategy": 1, "email": "a@x.io", "password": "pw"}
    with pytest.raises(Error, match="both email and password"):
        parse_csv("username,password,email\nann,pw,\n")
    with pytest.raises(Error, match="invalid email"):
        parse_csv("username,password,email\nann,pw,not-an-email\n")
    with pytest.raises(Error, match="header"):
        parse_csv("password,username\npw,ann\n")


def test_import_skips_accounts_of_another_site_and_imports_the_rest():
    from backoffice.store import Context, Store

    class Db:
        def rows(self, sql, *args):
            return [{"id": 443, "username": "guido66", "strategy": 5, "email": None, "password": None,
                     "site_id": 1004, "deleted": None, "synthetic": False}]

        def one(self, sql, *args):
            return {"x": 1}

    store = Store(Db(), Context(3, "aad", "simo", "operator"))
    rows = parse_csv("username,password,email\nguido66,pw,g@x.io\nmatte_99,pw2,m@x.io\n")
    plan = store._import_plan(1006, {"name": "BluffPoker", "version": 1}, rows, "upsert")
    assert [(c["username"], c["kind"]) for c in plan["changes"]] == [("guido66", "skipped"), ("matte_99", "create")]
    assert plan["counts"]["skipped"] == 1 and plan["counts"]["create"] == 1
