from __future__ import annotations

import io
import os
import re
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from .validation import Error, integer

GAMES = {0: "NLH", 1: "PLO4", 2: "PLO5", 4: "Tournament"}
MONEY = r"(?P<amount>\d+(?:\.\d+)?)"
ACTION = re.compile(r"^(?P<player>.+?) (?:posts (?:small blind|big blind|ante)|calls|bets|raises) \[\$" + MONEY + r" USD\]", re.I)
WIN = re.compile(r"^(?P<player>.+?) wins \$" + MONEY + r" USD(?:\s+from .+)?$", re.I)
SEAT = re.compile(r"^Seat\s+(?P<seat>\d+):\s+(?P<player>.*?)\s+\(\s*\$(?P<stack>[\d.]+)\s+USD\s*\)", re.I)
DEALT = re.compile(r"^Dealt to (?P<player>.+?) \[\s*(?P<cards>[^]]+)\]", re.I)
SHOW = re.compile(r"^(?P<player>.+?) shows \[\s*(?P<cards>[^]]+)\]", re.I)
BUTTON = re.compile(r"^Seat\s+(?P<seat>\d+)\s+is the button$", re.I)
STREET = re.compile(r"^\*+\s*(?:Dealing\s+)?(?P<street>Flop|Turn|River)\s*\*+\s*\[\s*(?P<cards>[^]]+)\]", re.I)
FOLD = re.compile(r"^(?P<player>.+?) folds\s*$", re.I)
PLAY = re.compile(r"^(?P<player>.+?) (?P<verb>folds|checks|calls|bets|raises|posts small blind|posts big blind|posts ante)(?: \[\$(?P<amount>[\d.]+) USD\])?", re.I)


def winnings(text: str, bot_names: list[str]):
    """Match PDecision HandHistoryWinnings' cash-hand contribution calculation."""
    own = {n.casefold(): n for n in bot_names}
    results = defaultdict(lambda: {"net": Decimal(0), "hands": 0})
    sections = re.split(r"\*{5} Hand History for Game \d+ \*{5}", text)
    if len(sections) == 1:
        raise ValueError("Unsupported hand-history format")
    for hand in sections[1:]:
        contributions, prizes, players, folded = defaultdict(Decimal), defaultdict(Decimal), set(), set()
        bb_match = re.search(r"^\$[\d.]+/\$([\d.]+)", hand, re.M)
        if not bb_match:
            raise ValueError("Missing big blind")
        bb = Decimal(bb_match[1])
        for raw in hand.splitlines():
            line = raw.strip()
            match = SEAT.match(line)
            if match:
                players.add(match["player"].casefold())
            match = ACTION.match(line)
            if match:
                contributions[match["player"].casefold()] += Decimal(match["amount"])
                continue
            match = FOLD.match(line)
            if match:
                folded.add(match["player"].casefold())
            match = WIN.match(line)
            if match:
                prizes[match["player"].casefold()] += Decimal(match["amount"])
        if not contributions or not prizes:
            raise ValueError("Incomplete hand settlement")
        # Same balancing as the stored results (shared schedule_controller.hand_settlement).
        from schedule_controller.hand_settlement import balance
        balance(contributions, prizes, players, folded, bb)
        for key in players & own.keys():
            results[own[key]]["hands"] += 1
            results[own[key]]["net"] += prizes[key] - contributions[key]
    return dict(results)


def hand_metrics(text: str, hero: str | None, bot_names: list[str]):
    players = {m["player"].casefold() for m in map(SEAT.match, map(str.strip, text.splitlines())) if m}
    bots = {n.casefold() for n in bot_names}
    parsed = winnings(text, bot_names)
    hero_result = next((v for n, v in parsed.items() if hero and n.casefold() == hero.casefold()), None)
    return {"human_count": len(players - bots), "hero_winnings": hero_result["net"] if hero_result else Decimal(0)}


def _replay_players(seats, stacks, bets, folded, hole_cards, hero):
    return [{"seat": s["seat"], "name": s["name"], "stack": stacks[s["name"].casefold()],
             "bet": bets[s["name"].casefold()], "folded": s["name"].casefold() in folded,
             "hero": bool(hero and s["name"].casefold() == hero.casefold()),
             "cards": hole_cards.get(s["name"].casefold(), [])}
            for s in seats]


def replay(text: str, hero: str | None):
    """Turn generated hand text into deterministic snapshots for Prev/Next."""
    seats, hole_cards, board, dealer_seat = [], {}, [], None
    for raw in text.splitlines():
        line = raw.strip()
        if match := SEAT.match(line):
            seats.append({"seat": int(match["seat"]), "name": match["player"], "initial_stack": Decimal(match["stack"])})
        elif match := DEALT.match(line) or SHOW.match(line):
            hole_cards[match["player"].casefold()] = re.findall(r"[2-9TJQKA][cdhs]", match["cards"], re.I)
        elif match := BUTTON.match(line):
            dealer_seat = int(match["seat"])
    stacks = {s["name"].casefold(): s["initial_stack"] for s in seats}
    bets, folded, pot, street = defaultdict(Decimal), set(), Decimal(0), "Preflop"
    steps = []
    def snapshot(label, action_player=None, action_text=None):
        value = max(Decimal(0), pot - sum(bets.values(), Decimal(0)))
        step = {"label": label, "street": street, "board": list(board), "pot": value,
                "players": _replay_players(seats, stacks, bets, folded, hole_cards, hero)}
        if action_player:
            step.update(action_player=action_player, action_text=action_text)
        steps.append(step)
    for raw in text.splitlines():
        line = raw.strip()
        if match := STREET.match(line):
            street = match["street"].title()
            board.extend(re.findall(r"[2-9TJQKA][cdhs]", match["cards"], re.I))
            bets = defaultdict(Decimal)
            snapshot(street)
            continue
        if match := PLAY.match(line):
            key, verb, amount = match["player"].casefold(), match["verb"].lower(), Decimal(match["amount"] or 0)
            forced = verb.startswith("posts ")
            if not forced and not steps:
                snapshot("First decision")
            if amount:
                stacks[key] = stacks.get(key, Decimal(0)) - amount
                bets[key] += amount
                pot += amount
            if forced:
                continue
            if verb == "folds":
                folded.add(key)
            action_text = verb.title() + (f" {amount}" if amount else "")
            snapshot(line, match["player"], action_text)
            continue
        if match := WIN.match(line):
            key, amount = match["player"].casefold(), Decimal(match["amount"])
            stacks[key] = stacks.get(key, Decimal(0)) + amount
            pot = max(Decimal(0), pot - amount)
            snapshot(line)
    if not steps:
        snapshot("Hand starts")
    return {"hero": hero, "dealer_seat": dealer_seat, "steps": steps, "raw": text}


def filters(query, zone):
    try:
        today = datetime.now(ZoneInfo(zone)).date()
        start = date.fromisoformat(query.get("from", (today - timedelta(days=7)).isoformat()))
        stop = date.fromisoformat(query.get("to", today.isoformat()))
        minimum = Decimal(str(query["min_blind"])) if query.get("min_blind") not in (None, "") else None
        maximum = Decimal(str(query["max_blind"])) if query.get("max_blind") not in (None, "") else None
    except (ValueError, TypeError, InvalidOperation):
        raise Error(400, "Use valid dates and blind amounts")
    if (stop < start or (stop - start).days > 3660 or minimum is not None and minimum < 0
            or maximum is not None and maximum < 0 or minimum is not None and maximum is not None and maximum < minimum):
        raise Error(400, "Invalid filter range")
    game = query.get("game", "all")
    if game not in ("all", *GAMES.values()):
        raise Error(400, "Invalid game filter")
    start_utc = datetime.combine(start, datetime.min.time(), ZoneInfo(zone)).astimezone(timezone.utc).replace(tzinfo=None)
    stop_utc = datetime.combine(stop + timedelta(days=1), datetime.min.time(), ZoneInfo(zone)).astimezone(timezone.utc).replace(tzinfo=None)
    return {"start": start_utc, "stop": stop_utc, "game": next((k for k, v in GAMES.items() if v == game), None),
            "hero": query.get("bot") or None, "minimum": minimum, "maximum": maximum}


class Histories:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self._container_client = None

    def _names(self, site_id):
        return [r["Username"] for r in self.db.rows("""SELECT b.Username FROM scheduler.AccountPolicy p
            JOIN dbo.BotAccount b ON b.BotAccountId=p.BotAccountId WHERE p.SiteId=%s AND p.IsSynthetic=0""", site_id)]

    def _where(self, site_id, query):
        site = self.store.site(site_id)
        selected = filters(query, site["timezone"])
        prefix = f"{self.store.ctx.customer_id}/{site['name']}/"
        sql = """CustomerId=%s AND LEFT(BlobPath,LEN(%s))=%s AND UploadedUtc>=%s AND UploadedUtc<%s
            AND (%s IS NULL OR GameType=%s) AND (%s IS NULL OR HeroPlayer=%s)
            AND (%s IS NULL OR BigBlind>=%s) AND (%s IS NULL OR BigBlind<=%s)"""
        args = (self.store.ctx.customer_id, prefix, prefix, selected["start"], selected["stop"],
                selected["game"], selected["game"], selected["hero"], selected["hero"],
                selected["minimum"], selected["minimum"], selected["maximum"], selected["maximum"])
        return sql, args

    def _enrich(self, rows, names):
        def read(row):
            clean = {k: v for k, v in row.items() if k != "blob_path"} | {"game": GAMES.get(row["game_id"], "Other")}
            try:
                return clean | hand_metrics(self._read(row["blob_path"]).decode("utf-8-sig"), row.get("hero"), names)
            except Exception:
                return clean | {"human_count": None, "hero_winnings": None}
        with ThreadPoolExecutor(max_workers=6) as pool:
            return list(pool.map(read, rows))

    def list(self, site_id, query):
        where, args = self._where(site_id, query)
        size = integer(query.get("page_size", 20), 1, 100, "page size")
        if size not in (10, 20, 50, 100):
            raise Error(400, "Page size must be 10, 20, 50 or 100")
        page = integer(query.get("page", 1), 1, 100000, "page")
        sort = query.get("sort", "winnings_desc")
        if sort not in ("uploaded_desc", "uploaded_asc", "winnings_desc", "winnings_asc"):
            raise Error(400, "Invalid sort")
        count = self.db.one(f"""SELECT COUNT(*) AS n FROM dbo.CustomerHandHistory h
            JOIN reporting.HandProcessing p ON p.HandHistoryId=h.Id AND p.Status='completed' AND p.HumanCount>=1
            WHERE {where}""", *args)["n"]
        names = self._names(site_id)
        direction = "DESC" if sort.endswith("desc") else "ASC"
        order = (f"CASE WHEN pr.NetWinnings IS NULL THEN 0 ELSE 1 END {direction},pr.NetWinnings {direction},h.Id {direction}"
                 if sort.startswith("winnings") else f"h.UploadedUtc {direction},h.Id {direction}")
        rows = self.db.rows(f"""SELECT h.Id AS id,h.HandId AS hand_id,h.GameType AS game_id,h.BigBlind AS big_blind,
            h.HeroPlayer AS hero,h.UploadedUtc AS uploaded,p.HumanCount AS human_count,
            pr.NetWinnings AS hero_winnings
            FROM dbo.CustomerHandHistory h
            JOIN reporting.HandProcessing p ON p.HandHistoryId=h.Id AND p.Status='completed' AND p.HumanCount>=1
            LEFT JOIN reporting.HandPlayerResult pr ON pr.HandHistoryId=h.Id AND pr.PlayerName=h.HeroPlayer
            WHERE {where} ORDER BY {order}
            OFFSET %s ROWS FETCH NEXT %s ROWS ONLY""", *args, (page - 1) * size, size)
        items = [{**row, "game": GAMES.get(row["game_id"], "Other")} for row in rows]
        return {"items": items, "page": page, "page_size": size, "total": count, "bots": names}

    def _read(self, path):
        container = self._container()
        payload = container.get_blob_client(path).download_blob(offset=0, length=262145).readall()
        if len(payload) > 262144:
            raise Error(413, "A hand-history file exceeds the supported size")
        # Files written before PDecision's showdown fix may pay the wrong player; the list,
        # replay and downloads all show the re-settled winners.
        from schedule_controller.hand_settlement import correct_winnings
        bom = payload.startswith(b"\xef\xbb\xbf")
        text = payload.decode("utf-8-sig")
        corrected = correct_winnings(text)
        if corrected == text:
            return payload
        return (b"\xef\xbb\xbf" if bom else b"") + corrected.encode("utf-8")

    def _container(self):
        """Create one thread-safe Azure client per request, not one per hand."""
        if self._container_client is not None:
            return self._container_client
        from azure.storage.blob import BlobServiceClient, ContainerClient
        if os.environ.get("BACKOFFICE_HH_CONTAINER_URL"):
            self._container_client = ContainerClient.from_container_url(
                os.environ["BACKOFFICE_HH_CONTAINER_URL"], connection_timeout=5,
                read_timeout=10, retry_total=1)
        elif os.environ.get("StorageConnString"):
            self._container_client = BlobServiceClient.from_connection_string(
                os.environ["StorageConnString"], connection_timeout=5,
                read_timeout=10, retry_total=1).get_container_client("hand-histories")
        else:
            raise Error(503, "Hand-history storage is not configured")
        return self._container_client

    def _selected(self, site_id, ids=None, query=None):
        if query is not None:
            where, args = self._where(site_id, query)
            rows = self.db.rows(f"SELECT TOP(1001) Id,HandId,GameType,BlobPath FROM dbo.CustomerHandHistory WHERE {where} ORDER BY Id", *args)
            if len(rows) > 1000:
                raise Error(413, "Select a narrower range (maximum 1,000 hands per ZIP)")
            return rows
        if not isinstance(ids, list) or not 1 <= len(ids) <= 1000:
            raise Error(400, "Select between 1 and 1,000 hands per ZIP")
        ids = sorted({integer(i, 1, 2**63 - 1, "hand id") for i in ids})
        site = self.store.site(site_id)
        prefix = f"{self.store.ctx.customer_id}/{site['name']}/"
        placeholders = ",".join(["%s"] * len(ids))
        rows = self.db.rows(f"SELECT Id,HandId,GameType,BlobPath FROM dbo.CustomerHandHistory WHERE CustomerId=%s AND LEFT(BlobPath,LEN(%s))=%s AND Id IN ({placeholders})", self.store.ctx.customer_id, prefix, prefix, *ids)
        if len(rows) != len(ids):
            raise Error(404, "One or more selected hands were not found")
        return rows

    def download(self, site_id, ids=None, query=None):
        rows = self._selected(site_id, ids, query)
        if not rows:
            raise Error(404, "No hands match these filters")
        with ThreadPoolExecutor(max_workers=6) as pool:
            payloads = list(pool.map(self._read, [r["BlobPath"] for r in rows]))
        if sum(map(len, payloads)) > 32 * 1024 * 1024:
            raise Error(413, "The selected ZIP is too large; narrow the filters")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for row, payload in zip(rows, payloads):
                name = re.sub(r"[^A-Za-z0-9_-]", "_", str(row["HandId"]))
                archive.writestr(f"{name}_{row['Id']}_{GAMES.get(row['GameType'], 'Other')}.txt", payload)
        self.store.audit("histories.download", site_id, {"count": len(rows)})
        return buffer.getvalue()

    def detail(self, site_id, history_id):
        site = self.store.site(site_id)
        prefix = f"{self.store.ctx.customer_id}/{site['name']}/"
        row = self.db.one("""SELECT Id AS id,HandId AS hand_id,GameType AS game_id,BigBlind AS big_blind,HeroPlayer AS hero,
            UploadedUtc AS uploaded,BlobPath AS blob_path FROM dbo.CustomerHandHistory
            WHERE Id=%s AND CustomerId=%s AND LEFT(BlobPath,LEN(%s))=%s""", history_id, self.store.ctx.customer_id, prefix, prefix)
        if not row:
            raise Error(404, "Hand was not found")
        text = self._read(row["blob_path"]).decode("utf-8-sig")
        return ({k: v for k, v in row.items() if k != "blob_path"} |
                {"game": GAMES.get(row["game_id"], "Other"), **hand_metrics(text, row.get("hero"), self._names(site_id)), "replay": replay(text, row.get("hero"))})

    def report(self, site_id, query):
        selected_bot = query.get("bot") or None
        # Players: your bots (default), the humans they played against, or both.
        players = query.get("players") or "bots"
        if players not in ("bots", "humans", "all"):
            raise Error(400, "Invalid players filter")
        is_bot = {"bots": 1, "humans": 0, "all": None}[players]
        report_query = dict(query)
        report_query.pop("bot", None)
        where, args = self._where(site_id, report_query)
        scope = f"""FROM reporting.HandPlayerResult r
            JOIN reporting.HandProcessing p ON p.HandHistoryId=r.HandHistoryId AND p.Status='completed'
            JOIN dbo.CustomerHandHistory h ON h.Id=r.HandHistoryId
            WHERE {where} AND p.HumanCount>=1 AND (%s IS NULL OR r.IsBot=%s) AND (%s IS NULL OR r.PlayerName=%s)"""
        scope_args = (*args, is_bot, is_bot, selected_bot, selected_bot)
        rows = self.db.rows(f"""SELECT h.GameType AS game_id,r.PlayerName AS username,r.IsBot AS is_bot,
                COUNT_BIG(*) AS hands,SUM(r.NetWinnings) AS net {scope}
            GROUP BY h.GameType,r.PlayerName,r.IsBot ORDER BY r.PlayerName,h.GameType""", *scope_args)
        totals = self.db.one(f"""SELECT COUNT(DISTINCT r.HandHistoryId) AS hands,COUNT_BIG(*) AS results,
                COUNT(DISTINCT r.PlayerName) AS players,COALESCE(SUM(r.NetWinnings),0) AS net {scope}""", *scope_args)
        status = self.db.one(f"""SELECT COUNT(*) AS total,
                SUM(CASE WHEN p.Status='completed' THEN 1 ELSE 0 END) AS processed,
                SUM(CASE WHEN p.Status='failed' THEN 1 ELSE 0 END) AS failed
            FROM dbo.CustomerHandHistory h LEFT JOIN reporting.HandProcessing p ON p.HandHistoryId=h.Id
            WHERE {where} AND (p.Status IS NULL OR p.Status<>'completed' OR p.HumanCount>=1)""", *args)
        return {"items": [{"game": GAMES.get(row["game_id"], "Other"), "username": row["username"],
                            "bot": bool(row["is_bot"]), "hands": row["hands"], "net": row["net"]} for row in rows],
                "players": players,
                "totals": {"hands": int(totals["hands"] or 0), "results": int(totals["results"] or 0),
                           "players": int(totals["players"] or 0), "net": totals["net"]},
                "processed": int(status["processed"] or 0), "total": int(status["total"] or 0),
                "skipped": [], "skipped_count": int(status["failed"] or 0), "next_cursor": None,
                "note": "Calculated once at ingestion and aggregated from persisted per-player results."}
