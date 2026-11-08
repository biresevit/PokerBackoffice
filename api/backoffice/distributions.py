"""Value distributions for account settings: "15% Strong Balanced, 10% Maniac, ..." per site.

A distribution lists values with percentages that total 100. Applying it to existing accounts gives
each value its exact share of the accounts (largest-remainder rounding), chosen at random. New
accounts take the value furthest below its target share, so the mix stays on target as accounts
are added.
"""
from __future__ import annotations

import hashlib
import json
import random
from decimal import Decimal

from .validation import PROFILES, TIERS, Error, integer, number

# field -> label, where it is stored, and which values are allowed
FIELDS = {
    "strategy": {"label": "Profile", "table": "account", "column": "Strategy", "kind": "choice",
                 "choices": [[k, v] for k, v in PROFILES.items()]},
    "stake": {"label": "Stake tier", "table": "policy", "column": "StakeTier", "kind": "choice",
              "choices": [[t, t.title()] for t in TIERS]},
    "frequency": {"label": "Playing frequency", "table": "policy", "column": "PlayingFrequency", "kind": "choice",
                  "choices": [[t, t.title()] for t in TIERS]},
    "max_minutes": {"label": "Daily playtime preference (minutes)", "table": "policy", "column": "MaxPlaytimeMinutes",
                    "kind": "integer", "min": 1, "max": 1440},
    "max_tables": {"label": "Maximum tables", "table": "policy", "column": "MaxTables", "kind": "integer", "min": 1, "max": 100},
    "max_sng_entries": {"label": "Maximum SNG entries at once", "table": "policy", "column": "MaxSngEntries", "kind": "integer", "min": 1, "max": 100},
    "max_mtt_entries": {"label": "Maximum MTT entries at once", "table": "policy", "column": "MaxMttEntries", "kind": "integer", "min": 1, "max": 100},
    "max_sng_rebuys": {"label": "Maximum rebuys per SNG", "table": "policy", "column": "MaxSngRebuys", "kind": "integer", "min": 0, "max": 100},
    "max_mtt_rebuys": {"label": "Maximum rebuys per MTT", "table": "policy", "column": "MaxMttRebuys", "kind": "integer", "min": 0, "max": 100},
    "max_sng_reentries": {"label": "Maximum re-entries per SNG", "table": "policy", "column": "MaxSngReentries", "kind": "integer", "min": 0, "max": 100},
    "max_mtt_reentries": {"label": "Maximum re-entries per MTT", "table": "policy", "column": "MaxMttReentries", "kind": "integer", "min": 0, "max": 100},
    "post_bb_chance": {"label": "Post big blind chance", "table": "policy", "column": "PostBbChance", "kind": "chance"},
    "run_it_twice_chance": {"label": "Run it twice chance", "table": "policy", "column": "RunItTwiceChance", "kind": "chance"},
    "rebuy_ring_chance": {"label": "Rebuy chance at ring tables", "table": "policy", "column": "RebuyRingChance", "kind": "chance"},
    "rebuy_tournament_chance": {"label": "Rebuy chance in SNG / MTT", "table": "policy", "column": "RebuyTournamentChance", "kind": "chance"},
    "show_cards_chance": {"label": "Show cards chance", "table": "policy", "column": "ShowCardsChance", "kind": "chance"},
    "addon_chance": {"label": "Tournament add-on chance", "table": "policy", "column": "AddonChance", "kind": "chance"},
}
MAX_OPTIONS = 20


def parse_value(field, value):
    spec = FIELDS[field]
    if spec["kind"] == "choice":
        allowed = {str(k): k for k, _ in spec["choices"]}
        if str(value) not in allowed:
            raise Error(400, f"{spec['label']}: {value} is not a valid choice")
        return allowed[str(value)]
    if spec["kind"] == "integer":
        return integer(value, spec["min"], spec["max"], spec["label"])
    result = number(value, 0, 1, spec["label"])
    if result != result.quantize(Decimal("0.00001")):
        raise Error(400, f"{spec['label']}: use at most five decimal places")
    return result


def validate(field, options):
    """[{"value": v, "percent": p}, ...] with percents > 0 totalling 100 and distinct values."""
    if field not in FIELDS:
        raise Error(404, "Unknown account setting")
    if not isinstance(options, list) or not 1 <= len(options) <= MAX_OPTIONS:
        raise Error(400, f"List between 1 and {MAX_OPTIONS} values")
    result, seen = [], set()
    for option in options:
        if not isinstance(option, dict):
            raise Error(400, "Invalid value")
        value = parse_value(field, option.get("value"))
        percent = number(option.get("percent"), 0, 100, "percentage")
        if percent <= 0 or percent != percent.quantize(Decimal("0.01")):
            raise Error(400, "Percentages must be above 0 with at most two decimal places")
        key = str(value)
        if key in seen:
            raise Error(400, f"{FIELDS[field]['label']}: {value} is listed twice")
        seen.add(key)
        result.append({"value": value, "percent": percent})
    if sum(o["percent"] for o in result) != 100:
        raise Error(400, f"{FIELDS[field]['label']}: percentages must total 100%")
    return result


def quotas(total, options):
    """Exact number of accounts per option, largest remainder first; ties go to the earlier option."""
    raw = [Decimal(total) * o["percent"] / 100 for o in options]
    counts = [int(r) for r in raw]
    order = sorted(range(len(options)), key=lambda i: (-(raw[i] - counts[i]), i))
    for i in order[:total - sum(counts)]:
        counts[i] += 1
    return counts


def assign(account_ids, options, rng=random):
    """{account_id: value} giving every option its exact share, accounts chosen at random."""
    ids = list(account_ids)
    rng.shuffle(ids)
    result, start = {}, 0
    for option, count in zip(options, quotas(len(ids), options)):
        for account_id in ids[start:start + count]:
            result[account_id] = option["value"]
        start += count
    return result


def pick_for_new(options, counts, rng=random):
    """Value for one more account: the option furthest below its target share, ties at random."""
    total = sum(counts.get(str(o["value"]), 0) for o in options) + 1
    def deficit(o):
        return Decimal(total) * o["percent"] / 100 - counts.get(str(o["value"]), 0)
    best = max(deficit(o) for o in options)
    return rng.choice([o for o in options if deficit(o) == best])["value"]


def value_key(field, value):
    """Compare stored and listed values the same way: chances as numbers (0.5 == 0.50000)."""
    return str(Decimal(str(value)).normalize()) if FIELDS[field]["kind"] == "chance" else str(value)


def stored(options):
    return json.dumps([{"value": o["value"] if not isinstance(o["value"], Decimal) else str(o["value"]),
                        "percent": str(o["percent"])} for o in options])


def loaded(field, text):
    return validate(field, json.loads(text))


class Distributions:
    def __init__(self, store):
        self.store, self.db = store, store.db

    def _saved(self, site_id):
        rows = self.db.rows("SELECT Field AS field,OptionsJson AS options FROM backoffice.AccountDistribution WHERE SiteId=%s", site_id)
        return {r["field"]: loaded(r["field"], r["options"]) for r in rows if r["field"] in FIELDS}

    def _accounts(self, site_id):
        """Real (non-simulation), not deleted accounts of the site with their current values."""
        columns = ",".join(f"{'b' if s['table'] == 'account' else 'p'}.{s['column']} AS {f}" for f, s in FIELDS.items())
        return self.db.rows(f"""SELECT b.BotAccountId AS id,{columns} FROM scheduler.AccountPolicy p
            JOIN dbo.BotAccount b ON b.BotAccountId=p.BotAccountId
            WHERE p.SiteId=%s AND p.DeletedUtc IS NULL AND p.IsSynthetic=0""", site_id)

    def list(self, site_id):
        site = self.store.site(site_id)
        saved, accounts = self._saved(site_id), self._accounts(site_id)
        fields = []
        for field, spec in FIELDS.items():
            current = {}
            for a in accounts:
                key = value_key(field, a[field])
                current[key] = current.get(key, 0) + 1
            fields.append({"field": field, "label": spec["label"], "kind": spec["kind"],
                           "choices": spec.get("choices"), "min": spec.get("min"), "max": spec.get("max"),
                           "options": [{"value": o["value"], "percent": o["percent"]} for o in saved.get(field, [])],
                           "current": sorted(({"value": k, "count": v} for k, v in current.items()), key=lambda r: -r["count"])[:12],
                           "distinct": len(current)})
        return {"fields": fields, "accounts": len(accounts), "version": site["version"]}

    def save(self, site_id, field, body):
        site = self.store.site(site_id, lock=True, version=body.get("version"))
        if field not in FIELDS:
            raise Error(404, "Unknown account setting")
        options = body.get("options")
        if options in (None, []):
            self.db.execute("DELETE backoffice.AccountDistribution WHERE SiteId=%s AND Field=%s", site_id, field)
        else:
            options = validate(field, options)
            self.db.execute("""MERGE backoffice.AccountDistribution AS t
                USING (SELECT %s AS SiteId,%s AS Field,%s AS OptionsJson) AS s ON t.SiteId=s.SiteId AND t.Field=s.Field
                WHEN MATCHED THEN UPDATE SET OptionsJson=s.OptionsJson,UpdatedUtc=SYSUTCDATETIME()
                WHEN NOT MATCHED THEN INSERT(SiteId,Field,OptionsJson) VALUES(s.SiteId,s.Field,s.OptionsJson);""",
                site_id, field, stored(options))
        self.store.bump(site_id)
        self.store.audit("distribution.save", f"{site_id}:{field}", {"options": options or []})
        return {"version": site["version"] + 1}

    def _plan(self, site_id, site, body):
        fields = body.get("fields")
        if not isinstance(fields, list) or not fields or any(f not in FIELDS for f in fields):
            raise Error(400, "Choose at least one account setting to apply")
        saved = self._saved(site_id)
        missing = [FIELDS[f]["label"] for f in fields if f not in saved]
        if missing:
            raise Error(400, "Define a distribution first for: " + ", ".join(missing))
        accounts = self._accounts(site_id)
        if not accounts:
            raise Error(409, "This site has no accounts to update")
        summary = []
        for field in sorted(set(fields), key=list(FIELDS).index):
            options = saved[field]
            counts = quotas(len(accounts), options)
            summary.append({"field": field, "label": FIELDS[field]["label"],
                            "values": [{"value": o["value"], "percent": o["percent"], "accounts": c} for o, c in zip(options, counts)]})
        token = hashlib.sha256(json.dumps([site_id, site["version"], len(accounts), [(s["field"], stored(saved[s["field"]])) for s in summary]],
                                          default=str).encode()).hexdigest()
        return {"accounts": len(accounts), "fields": summary, "token": token, "version": site["version"]}, accounts, saved

    def preview(self, site_id, body):
        site = self.store.site(site_id)
        if self.store.ctx.role != "operator":
            raise Error(403, "Your account has view-only access")
        return self._plan(site_id, site, body)[0]

    def apply(self, site_id, body):
        site = self.store.site(site_id, lock=True, version=body.get("version"))
        plan, accounts, saved = self._plan(site_id, site, body)
        if body.get("token") != plan["token"]:
            raise Error(409, "Accounts or distributions changed. Preview again before applying.")
        rng = random.SystemRandom()
        changed = 0
        for item in plan["fields"]:
            field, spec = item["field"], FIELDS[item["field"]]
            mapping = assign([a["id"] for a in accounts], saved[field], rng)
            before = {a["id"]: a[field] for a in accounts}
            groups = {}
            for account_id, value in mapping.items():
                if value_key(field, before[account_id]) != value_key(field, value):
                    groups.setdefault(value_key(field, value), (value, []))[1].append(account_id)
                    changed += 1
            table = "dbo.BotAccount" if spec["table"] == "account" else "scheduler.AccountPolicy"
            for value, ids in groups.values():
                for start in range(0, len(ids), 500):
                    chunk = ids[start:start + 500]
                    marks = ",".join(["%s"] * len(chunk))
                    self.db.execute(f"UPDATE {table} SET {spec['column']}=%s,UpdatedUtc=SYSUTCDATETIME() WHERE BotAccountId IN ({marks})",
                                    value, *chunk)
        self.store.bump(site_id)
        self.store.audit("distribution.apply", site_id, {"fields": [f["field"] for f in plan["fields"]], "accounts": len(accounts), "changed": changed})
        return {"version": site["version"] + 1, "accounts": len(accounts), "changed": changed}

    def new_account_picker(self, site_id):
        """A function returning {field: value} for each new account, keeping every distribution on target.

        The current mix is read once; each pick is counted, so a large import stays on target too.
        """
        saved = self._saved(site_id)
        counts = {field: {} for field in saved}
        if saved:
            for a in self._accounts(site_id):
                for field in saved:
                    key = value_key(field, a[field])
                    counts[field][key] = counts[field].get(key, 0) + 1
        keyed = {field: [dict(o, value=value_key(field, o["value"]), original=o["value"]) for o in options]
                 for field, options in saved.items()}

        def pick(fixed=None):
            """fixed: values already chosen for this account (e.g. a profile from the CSV); they are
            counted toward the mix instead of being picked."""
            result = {}
            for field, options in keyed.items():
                if fixed and fixed.get(field) is not None:
                    key = value_key(field, fixed[field])
                    counts[field][key] = counts[field].get(key, 0) + 1
                    continue
                key = pick_for_new(options, counts[field])
                counts[field][key] = counts[field].get(key, 0) + 1
                result[field] = next(o["original"] for o in options if o["value"] == key)
            return result
        pick.fields = set(saved)
        return pick
