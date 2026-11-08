from __future__ import annotations

import csv
import io
import math
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PROFILES = {1: "Maniac", 2: "Agro Fish", 3: "Calling Station", 4: "Passive Fish",
            5: "Strong Balanced", 6: "Strong Tight", 7: "Strong Loose", 8: "Strong Mix"}
TIERS = ("low", "medium", "high")
FORMATS = ("RING", "SNG", "MTT")


class Error(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


def integer(value, minimum=0, maximum=1000000, field="value"):
    if isinstance(value, bool):
        raise Error(400, f"Invalid {field}")
    try:
        number = int(str(value))
    except (ValueError, TypeError):
        raise Error(400, f"{field} must be an integer")
    if not minimum <= number <= maximum:
        raise Error(400, f"{field} must be between {minimum} and {maximum}")
    return number


def number(value, minimum=0, maximum=1000000, field="value"):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise Error(400, f"Invalid {field}")
    if not result.is_finite() or not Decimal(str(minimum)) <= result <= Decimal(str(maximum)):
        raise Error(400, f"{field} is outside its allowed range")
    return result


def choice(value, values, field):
    if value not in values:
        raise Error(400, f"Invalid {field}")
    return value


def username(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 100 or any(ord(c) < 32 for c in value):
        raise Error(400, "Username must contain 1–100 printable characters")
    return value.strip()


def parse_csv(text):
    if not isinstance(text, str) or len(text.encode()) > 1024 * 1024:
        raise Error(400, "CSV must be smaller than 1 MB")
    reader = csv.reader(io.StringIO(text.lstrip("\ufeff")), strict=True)
    try:
        header = [h.strip().casefold() for h in next(reader, [])]
        # username first, then any of password, email and profile. A missing or blank profile is assigned
        # from the site's profile distribution when the account is created; a blank login keeps the stored one.
        if (not header or header[0] not in ("username", "nickname") or len(set(header[1:])) != len(header) - 1
                or not set(header[1:]) <= {"password", "email", "profile"}):
            raise Error(400, "CSV header must start with username (or nickname), followed by any of password, email, profile")
        column = {name: i for i, name in enumerate(header)}
        rows, seen = [], set()
        profiles = {v.casefold(): k for k, v in PROFILES.items()}
        for line, row in enumerate(reader, 2):
            if not row or not any(v.strip() for v in row):
                continue
            if len(row) > len(header):
                raise Error(400, f"Line {line}: expected at most {len(header)} columns")
            name = username(row[0])
            if name.casefold() in seen:
                raise Error(400, f"Line {line}: duplicate username {name}")
            value = lambda key: row[column[key]].strip() if key in column and column[key] < len(row) else ""
            text = value("profile")
            profile = profiles.get(text.casefold()) if text else None
            if text and profile is None:
                raise Error(400, f"Line {line}: unknown profile {text}")
            email, password = value("email"), value("password")
            if email and (len(email) > 254 or "@" not in email or any(c.isspace() or ord(c) < 32 for c in email)):
                raise Error(400, f"Line {line}: invalid email {email}")
            if len(password) > 200 or any(ord(c) < 32 for c in password):
                raise Error(400, f"Line {line}: password must be at most 200 printable characters")
            if bool(email) != bool(password):
                raise Error(400, f"Line {line}: give both email and password, or neither")
            rows.append({"username": name, "strategy": profile, "email": email or None, "password": password or None})
            seen.add(name.casefold())
            if len(rows) > 5000:
                raise Error(400, "Import is limited to 5,000 accounts at a time")
    except csv.Error:
        raise Error(400, "Malformed CSV quoting")
    if not rows:
        raise Error(400, "CSV contains no accounts")
    return rows


def windows(body):
    rows = body.get("windows")
    if not isinstance(rows, list) or len(rows) > 336:
        raise Error(400, "Provide at most 336 schedule windows")
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise Error(400, "Invalid schedule window")
        w = {"Weekday": integer(row.get("weekday"), 0, 6, "weekday"),
             "StartMinute": integer(row.get("start_minute"), 0, 1439, "start"),
             "EndMinute": integer(row.get("end_minute"), 1, 1440, "end"),
             "TargetEntries": integer(row.get("target"), 0, 100000, "entries")}
        if w["StartMinute"] >= w["EndMinute"]:
            raise Error(400, "End time must follow start time; split overnight windows across days")
        result.append(w)
    previous = None
    for w in sorted(result, key=lambda r: (r["Weekday"], r["StartMinute"])):
        if previous and previous["Weekday"] == w["Weekday"] and previous["EndMinute"] > w["StartMinute"]:
            raise Error(400, "Schedule windows overlap")
        previous = w
    return result


def tournament_exclusions(value):
    """Tournament names to avoid: a list or newline-separated text, one name (substring) each."""
    items = value.splitlines() if isinstance(value, str) else value if isinstance(value, list) else None
    if items is None or not all(isinstance(x, str) for x in items):
        raise Error(400, "Excluded tournament names must be text, one name per line")
    names = list(dict.fromkeys(x.strip() for x in items if x.strip()))
    if len(names) > 50 or any(len(x) > 100 for x in names):
        raise Error(400, "Use at most 50 excluded tournament names of up to 100 characters each")
    text = "\n".join(names)
    if len(text) > 2000:
        raise Error(400, "The excluded tournament names are too long")
    return names


def is_excluded_tournament(name, excluded):
    """True when the tournament name contains any excluded name, ignoring case (as the scheduler does)."""
    name = str(name or "").casefold()
    return any(x.casefold() in name for x in excluded)


def stake_bands(body):
    rows = body.get("bands")
    if not isinstance(rows, list) or len(rows) != 3 or not all(isinstance(r, dict) for r in rows) or {r.get("tier") for r in rows} != set(TIERS):
        raise Error(400, "Provide low, medium and high stake bands")
    result = []
    for row in rows:
        lower = number(row.get("minimum"), field="minimum BB")
        upper = number(row.get("maximum"), field="maximum BB")
        pct = number(row.get("percent"), 0, 100, "percentage")
        if lower >= upper or pct * 100 != (pct * 100).to_integral_value():
            raise Error(400, "Stake limits must increase; percentages use at most two decimal places")
        if any(x != x.quantize(Decimal(".0001")) for x in (lower, upper)):
            raise Error(400, "Stake amounts support at most four decimal places")
        # Optional tournament (SNG/MTT) buy-in range of the tier: both blank, or both set.
        t_low, t_high = row.get("tournament_minimum"), row.get("tournament_maximum")
        if t_low in (None, "") and t_high in (None, ""):
            t_low = t_high = None
        else:
            t_low = number(t_low, field="tournament minimum buy-in")
            t_high = number(t_high, field="tournament maximum buy-in")
            if t_high < t_low:
                raise Error(400, f"{row['tier'].title()} tournament buy-in: maximum must not be below minimum")
        result.append({"tier": row["tier"], "minimum": lower, "maximum": upper,
                       "basis_points": int(pct * 100), "upper_inclusive": row["tier"] == "high",
                       "tournament_minimum": t_low, "tournament_maximum": t_high})
    if sum(r["basis_points"] for r in result) != 10000:
        raise Error(400, "Stake percentages must total 100%")
    result.sort(key=lambda r: TIERS.index(r["tier"]))
    if any(a["maximum"] > b["minimum"] for a, b in zip(result, result[1:])):
        raise Error(400, "Stake ranges overlap")
    return result


def account_settings(body):
    weights = body.get("buy_in_weights")
    if not isinstance(weights, dict) or not weights or len(weights) > 20:
        raise Error(400, "Buy-in weights must be an object")
    normalized = {}
    for key, value in weights.items():
        if key != "irregular":
            integer(key, 1, 10000, "buy-in BB")
        normalized[key] = float(number(value, 0, 100, "buy-in weight"))
    if not math.isclose(sum(normalized.values()), 100, abs_tol=.000001):
        raise Error(400, "Buy-in weights must total 100%")
    return {"strategy": integer(body.get("strategy"), 1, 8, "profile"),
        "stake": choice(body.get("stake"), TIERS, "stake"),
        "frequency": choice(body.get("frequency"), TIERS, "frequency"),
        "max_minutes": integer(body.get("max_minutes"), 1, 1440, "daily minutes"),
        "max_tables": integer(body.get("max_tables"), 1, 100, "maximum tables"),
        "max_sng_entries": integer(body.get("max_sng_entries", 1), 1, 100, "maximum SNG entries"),
        "max_mtt_entries": integer(body.get("max_mtt_entries", 1), 1, 100, "maximum MTT entries"),
        "post_bb_chance": number(body.get("post_bb_chance"), 0, 1, "post BB chance"),
        "run_it_twice_chance": number(body.get("run_it_twice_chance"), 0, 1, "run it twice chance"),
        "rebuy_ring_chance": number(body.get("rebuy_ring_chance"), 0, 1, "ring rebuy chance"),
        "rebuy_tournament_chance": number(body.get("rebuy_tournament_chance"), 0, 1, "tournament rebuy chance"),
        "show_cards_chance": number(body.get("show_cards_chance"), 0, 1, "show cards chance"),
        "addon_chance": number(body.get("addon_chance"), 0, 1, "add-on chance"),
        "games": games(body.get("games", "NLH,PLO4,PLO5")),
        "max_sng_rebuys": integer(body.get("max_sng_rebuys", 3), 0, 100, "maximum SNG rebuys"),
        "max_mtt_rebuys": integer(body.get("max_mtt_rebuys", 3), 0, 100, "maximum MTT rebuys"),
        "max_sng_reentries": integer(body.get("max_sng_reentries", 1), 0, 100, "maximum SNG re-entries"),
        "max_mtt_reentries": integer(body.get("max_mtt_reentries", 1), 0, 100, "maximum MTT re-entries"),
        "buy_in_weights": normalized}


# Game formats an account may play at ring tables (tournaments are NLH only): all, NLH only, or PLO only.
GAME_CHOICES = {"NLH,PLO4,PLO5": "All formats", "NLH": "NLH only", "PLO4,PLO5": "PLO4 and PLO5 only"}
GAMES = tuple(GAME_CHOICES)


def games(value):
    if isinstance(value, list):
        value = ",".join(g for g in ("NLH", "PLO4", "PLO5") if g in value)
    if value not in GAME_CHOICES:
        raise Error(400, "Game formats must be all formats, NLH only, or PLO4 and PLO5 only")
    return value
