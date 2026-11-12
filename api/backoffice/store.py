from __future__ import annotations

import hashlib
import json
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .validation import Error, FORMATS, PROFILES, TIERS, choice, integer, username, windows, stake_bands, tournament_exclusions, account_settings, parse_csv
from .distributions import Distributions, FIELDS as DISTRIBUTED


ENTRY_FORMAT_SQL = "CASE WHEN lt.TableType IN ('SNG','MTT') THEN lt.TableType ELSE 'RING' END"
ENTRY_LOBBY_JOIN = "LEFT JOIN scheduler.LobbyTable lt ON lt.SiteId=p.SiteId AND lt.TableId=p.TableId"


def scheduled_target(schedule, instant=None):
    """Target entries for an instant, using the site's local weekday/time."""
    if not schedule["enabled"]:
        return 0
    if schedule.get("target"):  # MTT: the per-tournament plans (mtts.planned_target)
        return schedule["target"](instant or datetime.now(timezone.utc))
    local = (instant or datetime.now(timezone.utc)).astimezone(ZoneInfo(schedule["timezone"]))
    minute = local.hour * 60 + local.minute
    return next((row["target"] for row in schedule["windows"]
                 if row["weekday"] == local.weekday()
                 and row["start_minute"] <= minute < row["end_minute"]), 0)


def entry_history_points(schedule, intervals, start, stop, step_minutes):
    """Keep exact entry transitions and schedule changes alongside regular ticks."""
    stamps={start,stop}
    cursor=start
    while cursor<stop:
        stamps.add(cursor)
        cursor+=timedelta(minutes=step_minutes)
    previous=scheduled_target(schedule,start)
    cursor=start.replace(second=0,microsecond=0)+timedelta(minutes=1)
    while cursor<=stop:
        target=scheduled_target(schedule,cursor)
        if target!=previous:
            stamps.add(cursor)
        previous=target
        cursor+=timedelta(minutes=1)
    events={}
    running=sum(seated<=start and (closed is None or closed>start) for seated,closed in intervals)
    for seated,closed in intervals:
        for stamp,delta in ((seated,1),(closed,-1)):
            if stamp is not None and start<stamp<=stop:
                stamps.add(stamp)
                events[stamp]=events.get(stamp,0)+delta
    points=[]
    for stamp in sorted(stamps):
        running+=events.get(stamp,0)
        points.append({"at":stamp,"scheduled":scheduled_target(schedule,stamp),"running":running})
    return points


def task_result_description(row):
    code=row.get("result_code")
    descriptions={
        "target_reduced":"Join cancelled because the scheduled entry target was reduced; this table entry was no longer needed.",
        "ValueError":"The task failed validation. The original worker did not record the specific reason.",
        "KeyError":"The worker could not find expected table or response data. This older worker did not record which field or table was missing.",
        "join_failure_limit":"Session ended after two failed table joins or tournament registrations; remaining joins were cancelled.",
        "session_ended":"The session has ended; no new join or tournament registration was attempted.",
        "TimeoutError":"The task timed out while waiting for a response or confirmation.",
        "ConnectionError":"The task could not complete because the connection failed.",
        "ProtocolError":"The task failed while communicating with the poker site. No detailed reason was recorded.",
        "RuntimeError":"The worker could not complete the task. No detailed reason was recorded.",
        "machine_offline":"Task expired because the machine stopped sending heartbeats for more than three minutes.",
        "worker_restarted":"Task cancelled because the machine worker restarted; its previous commands cannot be replayed.",
        "cleanup_unconfirmed":"The task failed and the worker could not confirm that the table was left. Reconciliation is required.",
        "reconciled_absent":"The worker confirmed that the bot is no longer seated at this table.",
    }
    return row.get("result_text") or descriptions.get(code) or (str(code).replace("_"," ").capitalize() if code else "")


def local_range(query, zone, now=None):
    """UTC bounds for a From/To filter in the site's wall-clock time.

    From defaults to 00:00 today. Without To the range is open-ended, so a page refreshing
    "until now" keeps showing new and scheduled rows. Dates mean whole days; date-times are
    minutes, with To inclusive."""
    now = now or datetime.now(timezone.utc)
    def parse(value, end):
        value = str(value).strip()
        try:
            if len(value) == 10:
                return datetime.strptime(value, "%Y-%m-%d") + timedelta(days=1 if end else 0)
            return datetime.strptime(value[:16], "%Y-%m-%dT%H:%M") + timedelta(minutes=1 if end else 0)
        except ValueError:
            raise Error(400, "From and To must be valid dates")
    utc = lambda local: local.replace(tzinfo=zone).astimezone(timezone.utc).replace(tzinfo=None)
    today = now.astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    start = utc(parse(query["from"], False)) if query.get("from") else utc(today)
    stop = utc(parse(query["to"], True)) if query.get("to") else now.replace(tzinfo=None) + timedelta(days=366)
    if stop <= start or stop - start > timedelta(days=367 + 366):
        raise Error(400, "To must be after From, within about a year")
    return start, stop


def live_table_sort_key(row):
    """Ring formats first, by occupancy. Then SNGs, most registrations first and then the highest
    buy-in; then MTTs, the soonest start first. Registering tournaments come before running ones,
    and finished ones go last."""
    table_type = str(row.get("table_type") or "RING").upper()
    game = str(row.get("game") or "").upper()
    state = {"registering": 0, "running": 1}.get(row.get("tournament_state"), 2)
    if table_type == "SNG":
        return (3, state, -row["occupied"], -(row.get("buy_in") or 0), row["name"])
    if table_type == "MTT":
        start = row.get("start")
        return (4, state, start is None, start.timestamp() if start else 0, row["name"])
    group = {"NLH": 0, "PLO4": 1, "PLO5": 2}.get(game, 5) if table_type == "RING" else 5
    return (group,
            0 if row["bot_entries"] else 1 if row["occupied"] else 2,
            -row["bot_entries"], -row["occupied"], row["big_blind"], row["name"])


def machine_health(row):
    heartbeat=row.get("heartbeat")
    row["online"] = bool(row.get("ready") and heartbeat and
        heartbeat >= datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=180))
    warnings=[]
    if row.get("average_cpu") is not None and row["average_cpu"]>=90: warnings.append("CPU has averaged at least 90% for 15 minutes")
    if row.get("average_memory") is not None and row["average_memory"]>=90: warnings.append("Memory usage has averaged at least 90% for 15 minutes")
    if row.get("average_disk") is not None and row["average_disk"]>=90: warnings.append("Disk has less than 10% free space")
    row["warnings"]=warnings
    return row


@dataclass(frozen=True)
class Context:
    customer_id: int
    provider: str
    subject: str
    role: str


def memberships(db, principal):
    return db.rows("""SELECT m.CustomerId AS id,c.CustomerName AS name,m.Role AS role
        FROM backoffice.Membership m JOIN dbo.Customer c ON c.CustomerId=m.CustomerId
        WHERE m.Provider=%s AND m.Subject=%s AND m.IsActive=1 AND c.IsActive=1 ORDER BY c.CustomerName""",
        principal["identityProvider"], principal["userId"])


class Store:
    def __init__(self, db, context: Context):
        self.db, self.ctx = db, context
        self._site_cache = {}

    def sites(self):
        return self.db.rows("""SELECT SiteId AS id,Casino AS name,Platform AS platform,TimeZone AS timezone,
            CurrencyCode AS currency,SchedulingEnabled AS enabled,ConfigVersion AS version
            FROM scheduler.Site WHERE CustomerId=%s ORDER BY Casino""", self.ctx.customer_id)

    def site(self, site_id, *, lock=False, version=None):
        if not lock and site_id in self._site_cache:
            return self._site_cache[site_id]
        hint = "WITH(UPDLOCK,HOLDLOCK)" if lock else ""
        result = self.db.one(f"""SELECT SiteId AS id,Casino AS name,Platform AS platform,CustomerId AS customer_id,TimeZone AS timezone,
            CurrencyCode AS currency,ConfigVersion AS version,SchedulingEnabled AS enabled,JoinsPaused AS joins_paused
            FROM scheduler.Site {hint} WHERE SiteId=%s AND CustomerId=%s""", site_id, self.ctx.customer_id)
        if result is None:
            raise Error(404, "Site not found")
        if lock:
            if self.ctx.role != "operator":
                raise Error(403, "Your account has view-only access")
            if integer(version, 1, 2**63 - 1, "configuration version") != result["version"]:
                raise Error(409, "Settings changed since this page was loaded. Refresh and try again.")
        # Reads must not hold cleanup write locks through the whole response.
        # The scheduler owns cleanup; reporting views apply heartbeat expiry.
        self._site_cache[site_id] = result
        return result

    def bump(self, site_id):
        self._site_cache.pop(site_id,None)
        self.db.execute("UPDATE scheduler.Site SET ConfigVersion=ConfigVersion+1,UpdatedUtc=SYSUTCDATETIME() WHERE SiteId=%s", site_id)

    def audit(self, action, entity, details):
        self.db.execute("""INSERT backoffice.AuditLog(CustomerId,Provider,Subject,Action,Entity,DetailJson)
            VALUES(%s,%s,%s,%s,%s,%s)""", self.ctx.customer_id, self.ctx.provider, self.ctx.subject,
            action, str(entity), json.dumps(details, default=str))

    def accounts(self, site_id):
        site = self.site(site_id)
        today = datetime.now(timezone.utc).astimezone(ZoneInfo(site["timezone"])).date()
        rows = self.db.rows("""SELECT b.BotAccountId AS id,b.Username AS username,b.Strategy AS strategy,
            b.IsActive AS active,p.StakeTier AS stake,p.PlayingFrequency AS frequency,
            p.MaxPlaytimeMinutes AS max_minutes,p.MaxTables AS max_tables,
            p.MaxSngEntries AS max_sng_entries,p.MaxMttEntries AS max_mtt_entries,p.AllowedGames AS games,
            p.MaxSngRebuys AS max_sng_rebuys,p.MaxMttRebuys AS max_mtt_rebuys,
            p.MaxSngReentries AS max_sng_reentries,p.MaxMttReentries AS max_mtt_reentries,
            p.SessionMinMinutes AS session_min_minutes,p.SessionMaxMinutes AS session_max_minutes,
            p.SessionCooldownMinutes AS session_cooldown_minutes,
            p.PostBbChance AS post_bb_chance,p.RunItTwiceChance AS run_it_twice_chance,
            p.RebuyRingChance AS rebuy_ring_chance,p.RebuyTournamentChance AS rebuy_tournament_chance,
            p.ShowCardsChance AS show_cards_chance,p.AddonChance AS addon_chance,
            p.BreakAfterMinSeconds/60 AS break_every_min_minutes,p.BreakAfterMaxSeconds/60 AS break_every_max_minutes,
            p.BreakMinSeconds AS break_min_seconds,p.BreakMaxSeconds AS break_max_seconds,
            p.BuyInPolicyJson AS buy_in_json,p.IsSynthetic AS synthetic,p.IsEnabled AS enabled,
            COALESCE(d.SessionSeconds,0) AS played_seconds,
            (SELECT COUNT(*) FROM backoffice.EntryPresence e WHERE e.SiteId=p.SiteId AND e.BotAccountId=p.BotAccountId AND e.IsOpen=1 AND e.IsConfirmedSeat=1) AS entries,
            (SELECT COUNT(*) FROM backoffice.EntryPresence e WHERE e.SiteId=p.SiteId AND e.BotAccountId=p.BotAccountId AND e.IsOpen=1 AND e.IsLiveOwner=1 AND e.IsConfirmedSeat=0) AS unconfirmed_entries,
            COALESCE(x.RingTables,0) AS active_tables,COALESCE(x.Tournaments,0) AS active_tournaments,
            COALESCE(x.RingTables,0)+COALESCE(x.Tournaments,0) AS active_entries,
            s.StartedUtc AS session_start,s.PlannedEndUtc AS session_end,prior.ActualEndUtc AS last_session_end
            FROM scheduler.AccountPolicy p JOIN dbo.BotAccount b ON b.BotAccountId=p.BotAccountId
            LEFT JOIN scheduler.AccountSession s ON s.BotAccountId=p.BotAccountId AND s.SiteId=p.SiteId AND s.IsOpen=1
            OUTER APPLY(SELECT TOP(1) z.ActualEndUtc FROM scheduler.AccountSession z
                WHERE z.BotAccountId=p.BotAccountId AND z.SiteId=p.SiteId AND z.IsOpen=0 ORDER BY z.ActualEndUtc DESC) prior
            LEFT JOIN scheduler.AccountDay d ON d.SiteId=p.SiteId AND d.BotAccountId=p.BotAccountId AND d.LocalDate=%s
            -- What the bot plays right now: ring tables it is seated at, and SNG/MTT entries it is registered for
            -- (accepted by the site) or playing.
            LEFT JOIN (SELECT BotAccountId,
                    SUM(CASE WHEN TableId NOT LIKE 'T%%' AND Status IN ('seated','sitting_out','draining') THEN 1 ELSE 0 END) AS RingTables,
                    SUM(CASE WHEN TableId LIKE 'T%%' AND (Status IN ('seated','sitting_out','draining')
                        OR (Status='joining' AND LastConfirmedUtc IS NOT NULL)) THEN 1 ELSE 0 END) AS Tournaments
                FROM scheduler.Entry WHERE SiteId=%s AND IsOpen=1 GROUP BY BotAccountId) x ON x.BotAccountId=p.BotAccountId
            WHERE p.SiteId=%s AND p.DeletedUtc IS NULL
            ORDER BY COALESCE(x.RingTables,0)+COALESCE(x.Tournaments,0) DESC,b.Username""", today, site_id, site_id)
        for row in rows:
            row["buy_in_weights"] = json.loads(row.pop("buy_in_json"))
            row["profile"] = PROFILES.get(row["strategy"], "Custom")
        return {"items": rows, "version": site["version"], "local_date": today.isoformat()}

    def _account(self, site_id, account_id):
        row = self.db.one("""SELECT p.BotAccountId AS id,p.IsSynthetic AS synthetic,b.Username AS username
            FROM scheduler.AccountPolicy p JOIN dbo.BotAccount b ON b.BotAccountId=p.BotAccountId
            WHERE p.SiteId=%s AND p.BotAccountId=%s AND p.DeletedUtc IS NULL""", site_id, account_id)
        if not row:
            raise Error(404, "Account not found")
        return row

    def update_account(self, site_id, account_id, body):
        site = self.site(site_id, lock=True, version=body.get("version"))
        account = self._account(site_id, account_id)
        values = account_settings(body)
        enabled = body.get("enabled")
        if enabled is not None and not isinstance(enabled, bool):
            raise Error(400, "Enabled must be true or false")
        if enabled and account["synthetic"]:
            raise Error(400, "Synthetic accounts cannot be enabled")
        durations = None
        if "session_min_minutes" in body:
            minimum = integer(body.get("session_min_minutes"), 1, 1440, "session minimum")
            maximum = integer(body.get("session_max_minutes"), minimum, 1440, "session maximum")
            cooldown = integer(body.get("session_cooldown_minutes"), 0, 1440, "session cooldown")
            durations = (minimum, maximum, cooldown)
        breaks = None
        if "break_every_min_minutes" in body:
            every_min = integer(body.get("break_every_min_minutes"), 1, 1440, "minimum minutes between breaks")
            every_max = integer(body.get("break_every_max_minutes"), every_min, 1440, "maximum minutes between breaks")
            length_min = integer(body.get("break_min_seconds"), 10, 300, "shortest break")
            length_max = integer(body.get("break_max_seconds"), length_min, 300, "longest break")
            breaks = (every_min * 60, every_max * 60, length_min, length_max)
        self.db.execute("UPDATE dbo.BotAccount SET Strategy=%s,UpdatedUtc=SYSUTCDATETIME() WHERE BotAccountId=%s",
                        values["strategy"], account_id)
        self.db.execute("""UPDATE scheduler.AccountPolicy SET StakeTier=%s,PlayingFrequency=%s,
            MaxPlaytimeMinutes=%s,MaxTables=%s,MaxSngEntries=%s,MaxMttEntries=%s,PostBbChance=%s,RunItTwiceChance=%s,
            RebuyRingChance=%s,RebuyTournamentChance=%s,ShowCardsChance=%s,AddonChance=%s,BuyInPolicyJson=%s,
            AllowedGames=%s,MaxSngRebuys=%s,MaxMttRebuys=%s,MaxSngReentries=%s,MaxMttReentries=%s,
            UpdatedUtc=SYSUTCDATETIME() WHERE SiteId=%s AND BotAccountId=%s""",
            values["stake"], values["frequency"], values["max_minutes"], values["max_tables"],
            values["max_sng_entries"], values["max_mtt_entries"], values["post_bb_chance"], values["run_it_twice_chance"], values["rebuy_ring_chance"],
            values["rebuy_tournament_chance"], values["show_cards_chance"], values["addon_chance"],
            json.dumps(values["buy_in_weights"]), values["games"], values["max_sng_rebuys"], values["max_mtt_rebuys"],
            values["max_sng_reentries"], values["max_mtt_reentries"], site_id, account_id)
        if enabled is not None:
            self.db.execute("UPDATE scheduler.AccountPolicy SET IsEnabled=%s WHERE SiteId=%s AND BotAccountId=%s", enabled, site_id, account_id)
        if durations:
            self.db.execute("UPDATE scheduler.AccountPolicy SET SessionMinMinutes=%s,SessionMaxMinutes=%s,SessionCooldownMinutes=%s WHERE SiteId=%s AND BotAccountId=%s", *durations, site_id, account_id)
        if breaks:
            self.db.execute("UPDATE scheduler.AccountPolicy SET BreakAfterMinSeconds=%s,BreakAfterMaxSeconds=%s,BreakMinSeconds=%s,BreakMaxSeconds=%s WHERE SiteId=%s AND BotAccountId=%s", *breaks, site_id, account_id)
        self.bump(site_id)
        self.audit("account.update", account_id, values)
        return {"version": site["version"] + 1}

    def _ensure_idle(self, site_id, account_id):
        if self.db.one("SELECT TOP(1) EntryId FROM scheduler.Entry WHERE SiteId=%s AND BotAccountId=%s AND IsOpen=1", site_id, account_id):
            raise Error(409, "An account still has live or pending entries. Leave its tables before deleting it.")
        if self.db.one("SELECT BotAccountId FROM scheduler.AccountLease WHERE SiteId=%s AND BotAccountId=%s", site_id, account_id):
            raise Error(409, "An account session still owns a lease. Close and reconcile it before deletion.")

    def _delete_account(self, site_id, account_id):
        self._ensure_idle(site_id, account_id)
        self.db.execute("UPDATE scheduler.AccountPolicy SET IsEnabled=0,DeletedUtc=SYSUTCDATETIME(),UpdatedUtc=SYSUTCDATETIME() WHERE SiteId=%s AND BotAccountId=%s", site_id, account_id)
        self.db.execute("UPDATE dbo.BotAccount SET IsActive=0,UpdatedUtc=SYSUTCDATETIME() WHERE BotAccountId=%s", account_id)

    def delete_account(self, site_id, account_id, body):
        site = self.site(site_id, lock=True, version=body.get("version"))
        row = self._account(site_id, account_id)
        self._delete_account(site_id, account_id)
        self.bump(site_id)
        self.audit("account.delete", account_id, {"username": row["username"]})
        return {"version": site["version"] + 1}

    def _defaults(self, site_id, strategy):
        # Assign new accounts to the least populated bucket; retain existing policies.
        def least(column, candidates):
            counts = {r["value"]: r["count"] for r in self.db.rows(
                f"SELECT {column} AS value,COUNT(*) AS count FROM scheduler.AccountPolicy WHERE SiteId=%s AND DeletedUtc IS NULL GROUP BY {column}", site_id)}
            return min(candidates, key=lambda v: (counts.get(v, 0), random.random()))
        strong = strategy >= 5
        return (least("StakeTier", TIERS), least("PlayingFrequency", TIERS),
                least("MaxPlaytimeMinutes", (120, 240, 360)), round(random.uniform(0, .2 if strong else 1), 5),
                round(random.uniform(.8 if strong else 0, 1), 5),
                round(random.uniform(.02, .10) if strong else random.uniform(.05, .90), 5),
                {"20": 5, "30": 5, "40": 5, "100": 65, "200": 20} if strong else
                {"20": 6.25, "30": 6.25, "40": 6.25, "50": 6.25, "100": 55, "200": 15, "irregular": 5})

    def _import_plan(self, site_id, site, rows, mode):
        if mode not in ("upsert", "replace"):
            raise Error(400, "Invalid import mode")
        existing = self.db.rows("""SELECT b.BotAccountId AS id,b.Username AS username,b.Strategy AS strategy,
            b.LoginEmail AS email,b.LoginPassword AS password,p.SiteId AS site_id,p.DeletedUtc AS deleted,p.IsSynthetic AS synthetic
            FROM dbo.BotAccount b LEFT JOIN scheduler.AccountPolicy p ON p.BotAccountId=b.BotAccountId
            WHERE b.Casino=%s""", site["name"])
        by_name = {r["username"].casefold(): r for r in existing}
        wanted = {r["username"].casefold() for r in rows}
        changes = []
        for row in rows:
            old = by_name.get(row["username"].casefold())
            if not old and row["username"].casefold().startswith("__schedule_demo_"):
                raise Error(400, "The __schedule_demo_ prefix is reserved for simulation accounts")
            if old and old["site_id"] != site_id:
                # Played on another site: left as it is, the rest of the file still imports.
                changes.append({"username": row["username"], "strategy": None, "kind": "skipped", "id": None,
                                "reason": "Already used on another site"})
                continue
            # A blank profile or login leaves an existing account's one as it is.
            login = old and row["email"] is not None and (row["email"], row["password"]) != (old["email"], old["password"])
            kind = ("create" if not old else "restore" if old["deleted"] else
                    "update" if row["strategy"] is not None and row["strategy"] != old["strategy"] or login else "unchanged")
            changes.append(dict(row, kind=kind, id=old["id"] if old else None))
        if any(c["kind"] == "create" and c["strategy"] is None for c in changes) and \
                not self.db.one("SELECT 1 AS x FROM backoffice.AccountDistribution WHERE SiteId=%s AND Field='strategy'", site_id):
            raise Error(400, "Some new accounts have no profile. Add a profile column, or define a profile distribution first.")
        if mode == "replace":
            for old in existing:
                if old["site_id"] == site_id and not old["deleted"] and old["username"].casefold() not in wanted:
                    self._ensure_idle(site_id, old["id"])
                    changes.append({"id": old["id"], "username": old["username"], "strategy": old["strategy"], "kind": "delete"})
        token = hashlib.sha256(json.dumps([site_id, site["version"], mode, changes], sort_keys=True).encode()).hexdigest()
        return {"changes": changes, "token": token,
                "counts": {k: sum(r["kind"] == k for r in changes) for k in ("create", "update", "restore", "delete", "unchanged", "skipped")},
                "version": site["version"]}

    def import_accounts(self, site_id, body, *, apply=False):
        site = self.site(site_id, lock=apply, version=body.get("version"))
        if self.ctx.role != "operator":
            raise Error(403, "Your account has view-only access")
        rows = parse_csv(body.get("csv"))
        preview = self._import_plan(site_id, site, rows, body.get("mode", "upsert"))
        if not apply:
            # Passwords never go back to the browser; the token still covers them.
            return dict(preview, changes=[{k: v for k, v in c.items() if k != "password"} for c in preview["changes"]])
        if body.get("token") != preview["token"]:
            raise Error(409, "Import preview changed. Preview the CSV again before applying it.")
        picker = Distributions(self).new_account_picker(site_id) if preview["counts"]["create"] else None
        for change in preview["changes"]:
            kind, aid = change["kind"], change["id"]
            if kind == "create":
                # Settings with a site distribution come from it; the rest keep the built-in defaults.
                picked = picker({"strategy": change["strategy"]})
                strategy = change["strategy"] if change["strategy"] is not None else picked["strategy"]
                aid = self.db.one("""INSERT dbo.BotAccount(Casino,Username,Strategy,LoginEmail,LoginPassword)
                    OUTPUT inserted.BotAccountId AS id VALUES(%s,%s,%s,%s,%s)""",
                    site["name"], change["username"], strategy, change.get("email"), change.get("password"))["id"]
                tier, freq, minutes, post, rit, show, weights = self._defaults(site_id, strategy)
                tier, freq, minutes = picked.get("stake", tier), picked.get("frequency", freq), picked.get("max_minutes", minutes)
                post, rit = picked.get("post_bb_chance", post), picked.get("run_it_twice_chance", rit)
                show = picked.get("show_cards_chance", show)
                # New accounts are on: whoever adds accounts wants them played.
                self.db.execute("""INSERT scheduler.AccountPolicy(BotAccountId,SiteId,StakeTier,PlayingFrequency,
                    MaxPlaytimeMinutes,PostBbChance,RunItTwiceChance,ShowCardsChance,BuyInPolicyJson,IsEnabled)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,1)""", aid, site_id, tier, freq, minutes, post, rit, show, json.dumps(weights))
                inserted = {"strategy", "stake", "frequency", "max_minutes", "post_bb_chance", "run_it_twice_chance", "show_cards_chance"}
                for field, value in picked.items():
                    if field not in inserted:
                        self.db.execute(f"UPDATE scheduler.AccountPolicy SET {DISTRIBUTED[field]['column']}=%s WHERE BotAccountId=%s", value, aid)
            elif kind == "update":
                self.db.execute("""UPDATE dbo.BotAccount SET Strategy=COALESCE(%s,Strategy),LoginEmail=COALESCE(%s,LoginEmail),
                    LoginPassword=COALESCE(%s,LoginPassword),UpdatedUtc=SYSUTCDATETIME() WHERE BotAccountId=%s""",
                    change["strategy"], change.get("email"), change.get("password"), aid)
            elif kind == "restore":
                self.db.execute("UPDATE scheduler.AccountPolicy SET DeletedUtc=NULL,UpdatedUtc=SYSUTCDATETIME() WHERE SiteId=%s AND BotAccountId=%s", site_id, aid)
                self.db.execute("""UPDATE b SET Strategy=COALESCE(%s,b.Strategy),LoginEmail=COALESCE(%s,b.LoginEmail),
                    LoginPassword=COALESCE(%s,b.LoginPassword),IsActive=CASE WHEN p.IsSynthetic=1 THEN 0 ELSE 1 END,
                    b.UpdatedUtc=SYSUTCDATETIME() FROM dbo.BotAccount b JOIN scheduler.AccountPolicy p ON p.BotAccountId=b.BotAccountId
                    WHERE p.SiteId=%s AND b.BotAccountId=%s""", change["strategy"], change.get("email"), change.get("password"), site_id, aid)
            elif kind == "delete":
                self._delete_account(site_id, aid)
        self.bump(site_id)
        self.audit("accounts.import", site_id, {"mode": body.get("mode", "upsert"), "counts": preview["counts"]})
        return {"counts": preview["counts"], "version": site["version"] + 1}

    def schedule(self, site_id, fmt="RING"):
        """One game format's weekly schedule: RING (tables), SNG or MTT (bots in tournaments at once)."""
        site = self.site(site_id)
        fmt = choice(fmt, FORMATS, "schedule format")
        rows = self.db.rows("""SELECT Weekday AS weekday,StartMinute AS start_minute,EndMinute AS end_minute,
            TargetEntries AS target FROM scheduler.ScheduleWindow WHERE SiteId=%s AND Format=%s ORDER BY Weekday,StartMinute""",
            site_id, fmt)
        return {"windows": rows, "format": fmt, "timezone": site["timezone"], "version": site["version"], "enabled": site["enabled"],
                "joins_paused": bool(site.get("joins_paused"))}

    def pause_joins(self, site_id, body):
        """Schedule page switch: while paused the scheduler plans no ring joins or SNG/MTT registrations; bots still
        leave and sessions still end. The scheduler's joins no PC has picked up yet are cancelled right away."""
        self.site(site_id)
        if self.ctx.role != "operator":
            raise Error(403, "Your account has view-only access")
        paused = body.get("paused")
        if type(paused) is not bool:
            raise Error(400, "Choose paused or running")
        self.db.execute("UPDATE scheduler.Site SET JoinsPaused=%s,UpdatedUtc=SYSUTCDATETIME() WHERE SiteId=%s", paused, site_id)
        cancelled = 0
        if paused:
            cancelled = self.db.one("EXEC scheduler.CancelPausedJoins @SiteId=%s", site_id)["n"]
        self._site_cache.pop(site_id, None)
        self.audit("schedule.pause" if paused else "schedule.resume", site_id, {"cancelled_joins": cancelled})
        return {"joins_paused": paused, "cancelled_joins": cancelled}

    def schedules(self, site_id):
        """Every format's weekly schedule in one query: {'RING': {...}, 'SNG': {...}, 'MTT': {...}}."""
        site = self.site(site_id)
        rows = self.db.rows("""SELECT Format AS format,Weekday AS weekday,StartMinute AS start_minute,EndMinute AS end_minute,
            TargetEntries AS target FROM scheduler.ScheduleWindow WHERE SiteId=%s ORDER BY Weekday,StartMinute""", site_id)
        return {fmt: {"windows": [{k: v for k, v in r.items() if k != "format"} for r in rows if r["format"] == fmt],
                      "format": fmt, "timezone": site["timezone"], "version": site["version"], "enabled": site["enabled"]}
                for fmt in FORMATS}

    def save_schedule(self, site_id, body):
        site = self.site(site_id, lock=True, version=body.get("version"))
        values = windows(body)
        fmt = choice(body.get("format") or "RING", FORMATS, "schedule format")
        zone = str(body.get("timezone", site["timezone"]))
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError):
            raise Error(400, "Unknown IANA timezone")
        self.db.execute("UPDATE scheduler.Site SET TimeZone=%s WHERE SiteId=%s", zone, site_id)
        self.db.execute("EXEC scheduler.SetSchedule @SiteId=%s,@WindowsJson=%s,@Format=%s", site_id, json.dumps(values), fmt)
        self.audit("schedule.update", site_id, {"format": fmt, "timezone": zone, "windows": values})
        return {"version": site["version"] + 1}

    def stakes(self, site_id):
        site = self.site(site_id)
        rows = self.db.rows("""SELECT Tier AS tier,MinBigBlind AS minimum,MaxBigBlind AS maximum,
            UpperInclusive AS upper_inclusive,TargetBasisPoints/100.0 AS [percent],
            TournamentMinBuyIn AS tournament_minimum,TournamentMaxBuyIn AS tournament_maximum
            FROM scheduler.StakeBand WHERE SiteId=%s ORDER BY MinBigBlind""", site_id)
        extra = self.db.one("SELECT ExtraTableChancePercent AS value FROM scheduler.Site WHERE SiteId=%s", site_id)
        return {"bands": rows, "currency": site["currency"], "version": site["version"],
                "excluded_tournaments": self.excluded_tournaments(site_id),
                "extra_table_percent": (extra or {}).get("value", 30)}

    def excluded_tournaments(self, site_id):
        """Tournament names this site's bots never register for (substrings, any case)."""
        row = self.db.one("SELECT ExcludedTournamentNames AS names FROM scheduler.Site WHERE SiteId=%s", site_id)
        return [x.strip() for x in str((row or {}).get("names") or "").splitlines() if x.strip()]

    def save_stakes(self, site_id, body):
        site = self.site(site_id, lock=True, version=body.get("version"))
        bands = stake_bands(body)
        excluded = tournament_exclusions(body.get("excluded_tournaments", self.excluded_tournaments(site_id)))
        self.db.execute("UPDATE scheduler.Site SET ExcludedTournamentNames=%s WHERE SiteId=%s", "\n".join(excluded), site_id)
        extra_table = body.get("extra_table_percent")
        if extra_table is not None:
            extra_table = integer(extra_table, 0, 100, field="extra_table_percent")
            self.db.execute("UPDATE scheduler.Site SET ExtraTableChancePercent=%s WHERE SiteId=%s", extra_table, site_id)
        for b in bands:
            self.db.execute("""UPDATE scheduler.StakeBand SET MinBigBlind=%s,MaxBigBlind=%s,UpperInclusive=%s,
                TargetBasisPoints=%s,TournamentMinBuyIn=%s,TournamentMaxBuyIn=%s WHERE SiteId=%s AND Tier=%s""",
                b["minimum"], b["maximum"], b["upper_inclusive"], b["basis_points"],
                b["tournament_minimum"], b["tournament_maximum"], site_id, b["tier"])
        self.bump(site_id)
        self.audit("stakes.update", site_id, {"bands": bands, "excluded_tournaments": excluded, "extra_table_percent": extra_table})
        return {"version": site["version"] + 1}

    def tables(self, site_id):
        self.site(site_id)
        rows = self.db.rows("""SELECT t.TableId AS id,t.TableName AS name,t.GameType AS game,t.TableType AS table_type,t.BigBlind AS big_blind,
            t.CurrencyCode AS currency,t.MaxSeats AS seats,t.OccupiedSeats AS occupied,t.ObservedUtc AS observed,
            t.FullSnapshotUtc AS snapshot,t.IsOpen AS is_open,t.MinBuyIn AS buy_in,t.StartUtc AS start,
            t.TournamentState AS tournament_state
            FROM scheduler.LobbyTable t
            WHERE t.SiteId=%s
              AND (t.TableType='RING' OR t.TournamentState IN ('registering','running'))
              -- BluffPoker snapshots arrive every 60-85 s: a 60 s window made its tables flicker in and out.
              AND t.ObservedUtc >= DATEADD(SECOND,-180,SYSUTCDATETIME())
              AND (t.TableType IN ('SNG','MTT') OR t.FullSnapshotUtc >= DATEADD(SECOND,-180,SYSUTCDATETIME()))
              AND EXISTS(SELECT 1 FROM scheduler.MachineAssignment o WHERE o.SiteId=t.SiteId AND o.MachineId=t.ObserverMachineId AND o.WorkerEpoch=t.ObserverEpoch AND o.IsReady=1 AND o.LastHeartbeatUtc>=DATEADD(second,-180,SYSUTCDATETIME()))
            ORDER BY t.BigBlind,t.TableName""", site_id)
        for row in rows:
            if row["table_type"] in ("SNG", "MTT"):
                # A tournament row has no seats; count our bots registered in or playing it, and list
                # the ones the tournament seated (they can be watched live).
                row["bot_entries"] = self.db.one("""SELECT COUNT(*) AS n FROM scheduler.Entry
                    WHERE SiteId=%s AND TableId=%s AND IsOpen=1""", site_id, row["id"])["n"]
                row["registered_bots"] = [r["username"] for r in self.db.rows("""SELECT b.Username AS username
                    FROM scheduler.Entry e JOIN dbo.BotAccount b ON b.BotAccountId=e.BotAccountId
                    WHERE e.SiteId=%s AND e.TableId=%s AND e.IsOpen=1 AND e.Status<>'seated' ORDER BY b.Username""",
                    site_id, row["id"])]
                row["players"] = self.db.rows("""SELECT b.Username AS username,e.BotAccountId AS account_id,
                    e.MachineId AS machine_id,COALESCE(x.HostName,m.Description) AS machine,e.PlayTableId AS play_table
                    FROM scheduler.Entry e JOIN dbo.BotAccount b ON b.BotAccountId=e.BotAccountId
                    LEFT JOIN dbo.CustomerMachine m ON m.MachineId=e.MachineId
                    LEFT JOIN backoffice.MachineMetadata x ON x.MachineId=e.MachineId
                    WHERE e.SiteId=%s AND e.TableId=%s AND e.IsOpen=1 AND e.Status='seated' ORDER BY b.Username""",
                    site_id, row["id"])
                continue
            row["players"] = self.db.rows("""SELECT s.SeatIndex AS seat,s.Username AS username,s.Stack AS stack,
                s.CurrentBet AS bet,s.InGame AS in_game,s.SittingOut AS sitting_out,ra.AccountId AS account_id,
                em.MachineId AS machine_id,COALESCE(x.HostName,m.Description) AS machine
                FROM scheduler.TableSeat s
                CROSS APPLY (SELECT COALESCE(s.BotAccountId,(SELECT TOP(1) b.BotAccountId FROM dbo.BotAccount b
                    JOIN scheduler.AccountPolicy p ON p.BotAccountId=b.BotAccountId
                    WHERE p.SiteId=s.SiteId AND b.Username=s.Username)) AS AccountId) ra
                OUTER APPLY (SELECT TOP(1) e.MachineId FROM scheduler.Entry e WHERE e.SiteId=s.SiteId AND e.TableId=s.TableId
                    AND e.BotAccountId=ra.AccountId AND e.IsOpen=1) em
                LEFT JOIN dbo.CustomerMachine m ON m.MachineId=em.MachineId
                LEFT JOIN backoffice.MachineMetadata x ON x.MachineId=em.MachineId
                WHERE s.SiteId=%s AND s.TableId=%s ORDER BY s.SeatIndex""", site_id, row["id"])
            # An open scheduler entry may still be joining, draining, or awaiting
            # restart reconciliation. The lobby badge describes seats, so derive
            # it only from bot identities present in this exact seat snapshot.
            row["bot_entries"] = sum(1 for player in row["players"] if player["account_id"] is not None)
        # Active bot tables first, then populated tables, then empty inventory.
        rows.sort(key=live_table_sort_key)
        interval=self.db.one('SELECT LobbyRefreshSeconds AS seconds FROM scheduler.Site WHERE SiteId=%s',site_id)
        return {"items": rows, "as_of": datetime.now(timezone.utc),"refresh_seconds":interval["seconds"]}

    def request_live_view(self,site_id,table_id,account_id):
        self.site(site_id)
        account_id=integer(account_id,1,field='account')
        entry=self.db.one("""SELECT TOP(1) e.MachineId,b.Username FROM scheduler.Entry e
            JOIN dbo.BotAccount b ON b.BotAccountId=e.BotAccountId
            WHERE e.SiteId=%s AND e.TableId=%s AND e.BotAccountId=%s AND e.IsOpen=1
                AND e.Status IN ('seated','sitting_out','draining')""",site_id,str(table_id),account_id)
        if not entry:
            raise Error(409,'That bot is no longer active at this table')
        request_id=str(uuid.uuid4())
        self.db.execute("""INSERT scheduler.LiveViewRequest(RequestId,SiteId,TableId,BotAccountId,MachineId,
            RequestedBy,ExpiresUtc,Status) VALUES(%s,%s,%s,%s,%s,%s,%s,'requested')""",
            request_id,site_id,str(table_id),account_id,entry['MachineId'],self.ctx.subject,
            datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(seconds=45))
        self.audit('tables.live.request',site_id,{'table':str(table_id),'account':account_id})
        return {'request_id':request_id,'refresh_seconds':1,'hero':entry['Username'],'idle_expiry_seconds':45}

    def live_view(self,site_id,request_id):
        self.site(site_id)
        try: request_id=str(uuid.UUID(str(request_id)))
        except (ValueError,TypeError): raise Error(400,'Invalid live-view request')
        row=self.db.one("""SELECT r.RequestId AS request_id,r.TableId AS table_id,r.Status AS status,
            r.RequestedUtc AS requested,r.ExpiresUtc AS expires,r.LastSnapshotUtc AS last_snapshot,
            r.ErrorText AS error,b.Username AS hero,t.GameType AS game,s.SequenceNumber AS sequence,s.CapturedUtc AS captured,
            s.PayloadJson AS payload
            FROM scheduler.LiveViewRequest r JOIN dbo.BotAccount b ON b.BotAccountId=r.BotAccountId
            JOIN scheduler.LobbyTable t ON t.SiteId=r.SiteId AND t.TableId=r.TableId
            LEFT JOIN scheduler.LiveTableSnapshot s ON s.RequestId=r.RequestId
            WHERE r.RequestId=%s AND r.SiteId=%s AND r.RequestedBy=%s""",request_id,site_id,self.ctx.subject)
        if not row: raise Error(404,'Live view was not found')
        row['request_id']=str(row['request_id'])
        if row['expires'].replace(tzinfo=timezone.utc)<=datetime.now(timezone.utc) and row['status'] in ('requested','active'):
            row['status']='expired'
        elif row['status'] in ('requested','active'):
            # Browser polling is the lease heartbeat. Closing the live window
            # stops detailed machine telemetry within 45 seconds.
            renewed=datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(seconds=45)
            self.db.execute('UPDATE scheduler.LiveViewRequest SET ExpiresUtc=%s WHERE RequestId=%s',renewed,request_id)
            row['expires']=renewed
        row['payload']=json.loads(row['payload']) if row['payload'] else None
        if row['payload']:
            row['payload'].setdefault('game',row['game'])
            from .live_cards import enrich
            enrich(self,site_id,row)
        if self.ctx.role=='operator':
            from .manual import Manual
            row['manual']=Manual(self).status(site_id,request_id)
        else:row['manual']={'enabled':False,'read_only':True}
        return row

    def machines(self, site_id):
        self.site(site_id)
        rows = self.db.rows("""SELECT m.MachineId AS id,COALESCE(x.HostName,m.Description) AS name,x.HostName AS host,
            COALESCE(st.Casino,m.Casino) AS registered_site,x.PublicIp AS public_ip,x.PrivateIp AS private_ip,
            COALESCE(cap.MaxEntries,a.MaxEntries) AS max_entries,COALESCE(cap.IsEnabled,CONVERT(bit,1)) AS machine_enabled,a.IsReady AS ready,a.IsEnabled AS enabled,a.LastHeartbeatUtc AS heartbeat,
            a.MaintenanceTaskId AS maintenance_task_id,a.SiteId AS active_site_id,COALESCE(x.Version,1) AS version,
            latest.SampledUtc AS telemetry_at,latest.CpuPercent AS cpu_percent,
            latest.MemoryPercent AS memory_percent,latest.DiskPercent AS disk_percent,
            latest.DiskFreeBytes AS disk_free_bytes,latest.DiskTotalBytes AS disk_total_bytes,
            latest.PokerControllerVersion AS poker_controller_version,
            latest.PDecisionVersion AS pdecision_version,
            averages.AvgCpu AS average_cpu,averages.AvgMemory AS average_memory,
            averages.AvgDisk AS average_disk,
            (SELECT COUNT(*) FROM backoffice.EntryPresence e JOIN scheduler.Site s ON s.SiteId=e.SiteId
             WHERE e.MachineId=m.MachineId AND s.CustomerId=m.CustomerId AND e.IsOpen=1
               AND (a.SiteId IS NULL OR e.SiteId=a.SiteId)
               -- every format: a ring seat once observed, an SNG/MTT ('T…') once the tournament seated the bot
               AND (e.IsConfirmedSeat=1 OR LEFT(e.TableId,1)='T' AND e.Status='seated')) AS entries,
            (SELECT COUNT(*) FROM backoffice.EntryPresence e JOIN scheduler.Site s ON s.SiteId=e.SiteId
             WHERE e.MachineId=m.MachineId AND s.CustomerId=m.CustomerId AND e.IsOpen=1
               AND (a.SiteId IS NULL OR e.SiteId=a.SiteId) AND e.IsLiveOwner=1 AND e.IsConfirmedSeat=0
               AND NOT (LEFT(e.TableId,1)='T' AND e.Status='seated')) AS pending_entries
            FROM dbo.CustomerMachine m LEFT JOIN backoffice.MachineMetadata x ON x.MachineId=m.MachineId
            LEFT JOIN scheduler.MachineCapacity cap ON cap.MachineId=m.MachineId
            -- one row per poker site the PC plays, and per site taken off it that still has open entries
            LEFT JOIN scheduler.MachineAssignment a ON a.MachineId=m.MachineId
                AND (EXISTS(SELECT 1 FROM backoffice.MachineAllowedSite w WHERE w.MachineId=a.MachineId AND w.SiteId=a.SiteId)
                     OR EXISTS(SELECT 1 FROM scheduler.Entry o WHERE o.MachineId=a.MachineId AND o.SiteId=a.SiteId AND o.IsOpen=1)
                     OR NOT EXISTS(SELECT 1 FROM backoffice.MachineAllowedSite w WHERE w.MachineId=a.MachineId))
            LEFT JOIN scheduler.Site st ON st.SiteId=a.SiteId
            OUTER APPLY (SELECT TOP(1) t.SampledUtc,t.CpuPercent,t.MemoryPercent,t.DiskPercent,
                t.DiskFreeBytes,t.DiskTotalBytes,t.PokerControllerVersion,t.PDecisionVersion
                FROM scheduler.MachineTelemetry t
                WHERE t.SiteId=a.SiteId AND t.MachineId=m.MachineId ORDER BY t.SampledUtc DESC) latest
            OUTER APPLY (SELECT AVG(CONVERT(float,t.CpuPercent)) AS AvgCpu,
                AVG(CONVERT(float,t.MemoryPercent)) AS AvgMemory,AVG(CONVERT(float,t.DiskPercent)) AS AvgDisk
                FROM scheduler.MachineTelemetry t WHERE t.SiteId=a.SiteId AND t.MachineId=m.MachineId
                AND t.SampledUtc>=DATEADD(minute,-15,SYSUTCDATETIME())) averages
            WHERE m.CustomerId=%s AND m.IsActive=1 ORDER BY m.MachineId""", self.ctx.customer_id)
        for row in rows:
            row["allowed_sites"] = [r["SiteId"] for r in self.db.rows("SELECT SiteId FROM backoffice.MachineAllowedSite WHERE MachineId=%s", row["id"])]
            machine_health(row)
        return {"items": rows, "sites": self.sites()}

    def machine_metrics(self, site_id, machine_id, query):
        self.site(site_id)
        machine = self.db.one("""SELECT ma.MachineId FROM scheduler.MachineAssignment ma
            JOIN dbo.CustomerMachine cm ON cm.MachineId=ma.MachineId
            WHERE ma.SiteId=%s AND ma.MachineId=%s AND cm.CustomerId=%s AND cm.IsActive=1""",
            site_id, machine_id, self.ctx.customer_id)
        if not machine:
            raise Error(404, "Machine not found")
        hours = integer(query.get("hours", 24), 1, 168, "hours")
        points = self.db.rows("""SELECT t.SampledUtc AS at,t.CpuPercent AS cpu,t.MemoryPercent AS memory,
            t.DiskPercent AS disk,
                (SELECT COUNT(*) FROM scheduler.Entry e
                 WHERE e.SiteId=t.SiteId AND e.MachineId=t.MachineId
                   AND e.SeatedUtc<=t.SampledUtc
                   AND (e.ClosedUtc IS NULL OR e.ClosedUtc>t.SampledUtc)) AS entries
            FROM scheduler.MachineTelemetry t
            WHERE t.SiteId=%s AND t.MachineId=%s AND t.SampledUtc>=DATEADD(hour,%s,SYSUTCDATETIME())
            ORDER BY t.SampledUtc""", site_id, machine_id, -hours)
        return {"machine_id": machine_id, "hours": hours, "sample_minutes": 5, "points": points}

    def tasks(self,site_id,query):
        self.site(site_id)
        machine=str(query.get("machine") or "").strip()[:100]
        bot=str(query.get("bot") or "").strip()[:100]
        kind=str(query.get("kind") or "all").lower()
        if kind not in ("all","join","leave","scan","update"):raise Error(400,"Invalid task type")
        fmt=str(query.get("format") or "all").upper()
        if fmt not in ("ALL",*FORMATS):raise Error(400,"Invalid game format")
        fmt=fmt.lower() if fmt=="ALL" else fmt
        status=str(query.get("status") or "all").lower()
        if status not in ("all","pending","claimed","succeeded","failed","cancelled","expired","uncertain"):raise Error(400,"Invalid task status")
        page=integer(query.get("page",1),1,100000,"page")
        size=integer(query.get("page_size",50),10,100,"page size")
        if size not in (10,20,50,100):raise Error(400,"Page size must be 10, 20, 50 or 100")
        start,stop=local_range(query,ZoneInfo(self.site(site_id)["timezone"]))
        cte="""WITH TaskRows AS(
            SELECT c.CommandId AS TaskId,c.SiteId,c.MachineId,c.Kind,c.Status,c.CreatedUtc,c.UpdatedUtc,
                c.NotBeforeUtc,c.AttemptCount,c.ResultCode,c.ResultText,e.TableId,b.Username AS Bot,
                COALESCE(lt.TableType,'RING') AS Format,lt.TableName
            FROM scheduler.Command c JOIN scheduler.Entry e ON e.EntryId=c.EntryId JOIN dbo.BotAccount b ON b.BotAccountId=e.BotAccountId
            LEFT JOIN scheduler.LobbyTable lt ON lt.SiteId=e.SiteId AND lt.TableId=e.TableId
            UNION ALL
            SELECT t.TaskId,t.SiteId,t.MachineId,'update',
                CASE WHEN t.Status='queued' THEN 'pending' WHEN t.Status='completed' THEN 'succeeded'
                     WHEN t.Status IN ('failed','rolled_back') THEN 'failed' WHEN t.Status='cancelled' THEN 'cancelled' ELSE 'claimed' END,
                r.CreatedUtc,t.UpdatedUtc,r.NotBeforeUtc,CASE WHEN t.StartedUtc IS NULL THEN 0 ELSE 1 END,t.Status,t.Detail,'','All sessions','',NULL
            FROM scheduler.MachineUpdateTask t JOIN scheduler.UpdateRollout r ON r.RolloutId=t.RolloutId)
            """
        where="""c.SiteId=%s AND (%s='' OR CONVERT(nvarchar(20),c.MachineId)=%s OR COALESCE(x.HostName,m.Description,'') LIKE %s)
            AND (%s='' OR c.Bot LIKE %s) AND (%s='all' OR c.Kind=%s) AND (%s='all' OR c.Status=%s)
            AND (%s='all' OR c.Format=%s) AND c.CreatedUtc>=%s AND c.CreatedUtc<%s"""
        args=(site_id,machine,machine,'%'+machine+'%',bot,'%'+bot+'%',kind,kind,status,status,fmt,fmt,start,stop)
        joins=" FROM TaskRows c JOIN dbo.CustomerMachine m ON m.MachineId=c.MachineId LEFT JOIN backoffice.MachineMetadata x ON x.MachineId=m.MachineId "
        total=self.db.one(cte+'SELECT COUNT(*) AS n'+joins+'WHERE '+where,*args)['n']
        items=self.db.rows(cte+"""SELECT c.TaskId AS id,c.Kind AS kind,c.Status AS status,c.CreatedUtc AS created,
            c.UpdatedUtc AS updated,c.NotBeforeUtc AS due,c.AttemptCount AS attempts,c.ResultCode AS result_code,
            c.ResultText AS result_text,c.TableId AS table_id,c.Bot AS bot,c.MachineId AS machine_id,
            c.Format AS format,c.TableName AS table_name,
            COALESCE(x.HostName,m.Description) AS machine"""+joins+'WHERE '+where+" ORDER BY c.CreatedUtc DESC,c.TaskId OFFSET %s ROWS FETCH NEXT %s ROWS ONLY",*args,(page-1)*size,size)
        choices=self.db.rows(cte+"""SELECT DISTINCT c.MachineId AS machine_id,COALESCE(x.HostName,m.Description) AS machine"""+joins+'WHERE c.SiteId=%s ORDER BY machine',site_id)
        bots=self.db.rows("SELECT b.Username AS username FROM scheduler.AccountPolicy p JOIN dbo.BotAccount b ON b.BotAccountId=p.BotAccountId WHERE p.SiteId=%s AND p.DeletedUtc IS NULL ORDER BY b.Username",site_id)
        for item in items:item['result_description']=task_result_description(item)
        return {'items':items,'total':total,'page':page,'page_size':size,'machines':choices,'bots':bots}

    def sessions(self,site_id,query):
        site=self.site(site_id)
        start,stop=local_range(query,ZoneInfo(site["timezone"]))
        bot=str(query.get("bot") or "").strip()[:100]
        result=str(query.get("result") or "all").strip()
        if len(result)>80:
            raise Error(400,"Invalid session result")
        result_options=[r["reason"] for r in self.db.rows("SELECT DISTINCT EndReason AS reason FROM backoffice.SessionActivity WHERE SiteId=%s AND IsOpen=0 AND EndReason IS NOT NULL ORDER BY EndReason",site_id)]
        if result not in ("all","active","scheduled","closed",*result_options):
            raise Error(400,"Invalid session result")
        page=integer(query.get("page",1),1,100000,"page");size=integer(query.get("page_size",50),10,100,"page size")
        if size not in (10,20,50,100): raise Error(400,"Page size must be 10, 20, 50 or 100")
        where="""s.SiteId=%s AND s.StartedUtc<%s AND COALESCE(s.ActualEndUtc,SYSUTCDATETIME())>=%s AND (%s='' OR b.Username LIKE %s) AND (%s='all' OR (%s='closed' AND s.IsOpen=0) OR
            CASE WHEN s.IsOpen=1 AND s.StartedUtc>SYSUTCDATETIME() THEN 'scheduled'
                 WHEN s.IsOpen=1 THEN 'active' ELSE COALESCE(s.EndReason,'closed') END=%s)"""
        args=(site_id,stop,start,bot,"%"+bot+"%",result,result,result)
        total=self.db.one(f"""SELECT COUNT(*) AS n FROM backoffice.SessionActivity s
            JOIN dbo.BotAccount b ON b.BotAccountId=s.BotAccountId WHERE {where}""",*args)["n"]
        items=self.db.rows(f"""SELECT s.SessionId AS id,b.Username AS bot,s.MachineId AS machine_id,
            COALESCE(x.HostName,m.Description) AS machine,s.StartedUtc AS started,s.PlannedEndUtc AS planned_end,
            s.ActualEndUtc AS actual_end,s.IsOpen AS is_open,s.EndReason AS end_reason,
            (SELECT r.IsManual FROM scheduler.AccountSession r WHERE r.SessionId=s.SessionId) AS is_manual,
            CASE WHEN s.IsOpen=1 AND s.StartedUtc>SYSUTCDATETIME() THEN CONVERT(bit,1) ELSE CONVERT(bit,0) END AS is_scheduled,
            CASE WHEN s.IsOpen=1 AND s.StartedUtc>SYSUTCDATETIME() THEN 0
                 ELSE DATEDIFF(second,s.StartedUtc,COALESCE(s.ActualEndUtc,SYSUTCDATETIME())) END AS duration_seconds,
            (SELECT COUNT(*) FROM backoffice.EntryPresence e WHERE e.SessionId=s.SessionId AND (s.IsOpen=0 OR (e.IsOpen=1 AND e.IsConfirmedSeat=1))) AS entries,
            (SELECT COUNT(*) FROM backoffice.EntryPresence e WHERE e.SessionId=s.SessionId AND e.IsOpen=1 AND e.IsConfirmedSeat=1) AS current_entries,
            (SELECT COUNT(*) FROM scheduler.Entry e WHERE e.SessionId=s.SessionId) AS total_entries,
            (SELECT COUNT(*) FROM scheduler.Entry e WHERE e.SessionId=s.SessionId AND e.Status='failed') AS failed_entries,
            (SELECT COUNT(*) FROM backoffice.EntryPresence e WHERE e.SessionId=s.SessionId AND e.IsOpen=1 AND e.IsLiveOwner=1 AND e.IsConfirmedSeat=0) AS unconfirmed_entries
            FROM backoffice.SessionActivity s JOIN dbo.BotAccount b ON b.BotAccountId=s.BotAccountId
            JOIN dbo.CustomerMachine m ON m.MachineId=s.MachineId
            LEFT JOIN backoffice.MachineMetadata x ON x.MachineId=m.MachineId
            WHERE {where} ORDER BY s.StartedUtc DESC,s.SessionId
            OFFSET %s ROWS FETCH NEXT %s ROWS ONLY""",*args,(page-1)*size,size)
        bots=self.db.rows("""SELECT b.Username AS username FROM scheduler.AccountPolicy p
            JOIN dbo.BotAccount b ON b.BotAccountId=p.BotAccountId WHERE p.SiteId=%s AND p.DeletedUtc IS NULL ORDER BY b.Username""",site_id)
        return {"items":items,"total":total,"page":page,"page_size":size,"bots":bots,
                "result_options":result_options,"from":query.get("from") or "","to":query.get("to") or ""}

    def save_machine(self, site_id, machine_id, body):
        self.site(site_id)
        if self.ctx.role != "operator":
            raise Error(403, "Your account has view-only access")
        machine = self.db.one("""SELECT m.MachineId,x.Version FROM dbo.CustomerMachine m
            JOIN backoffice.MachineMetadata x WITH(UPDLOCK,HOLDLOCK) ON x.MachineId=m.MachineId
            WHERE m.MachineId=%s AND m.CustomerId=%s""", machine_id, self.ctx.customer_id)
        if not machine:
            raise Error(404, "Machine not found")
        if machine["Version"] != integer(body.get("version"), 1, 2**63 - 1, "version"):
            raise Error(409, "Machine settings changed. Refresh and try again.")
        # 0 entries keeps the PC connected without playing; a disabled PC joins nothing and scans no lobby.
        cap = integer(body.get("max_entries"), 0, 10000, "maximum entries")
        enabled = body.get("enabled", True)
        if not isinstance(enabled, bool):
            raise Error(400, "Invalid enabled flag")
        allowed = body.get("allowed_sites")
        if not isinstance(allowed, list) or len(allowed) > 100:
            raise Error(400, "Invalid allowed sites")
        allowed = sorted({integer(v, 1, field="site") for v in allowed})
        for sid in allowed:
            self.site(sid)
        active = self.db.rows("SELECT DISTINCT SiteId FROM scheduler.Entry WHERE MachineId=%s AND IsOpen=1", machine_id)
        if any(r["SiteId"] not in allowed for r in active):
            raise Error(409, "Leave active tables before removing their site from this machine")
        if not allowed:
            raise Error(400, "Choose at least one poker site for this machine")
        self.db.execute("EXEC backoffice.SetMachineSites @CustomerId=%s,@MachineId=%s,@SiteIds=%s,@MaxEntries=%s,@Enabled=%s",
                        self.ctx.customer_id, machine_id, ",".join(map(str, allowed)), cap, enabled)
        self.db.execute("UPDATE backoffice.MachineMetadata SET Version=Version+1 WHERE MachineId=%s", machine_id)
        self.audit("machine.update", machine_id, {"max_entries": cap, "enabled": enabled, "allowed_sites": allowed})
        return {"version": machine["Version"] + 1}

    def delete_machine(self, site_id, machine_id, body):
        """Remove a machine from the workspace. History stays; pairing the same PC again brings it back."""
        self.site(site_id)
        if self.ctx.role != "operator":
            raise Error(403, "Your account has view-only access")
        machine = self.db.one("""SELECT m.MachineId,x.Version,COALESCE(x.HostName,m.Description) AS Name FROM dbo.CustomerMachine m
            JOIN backoffice.MachineMetadata x WITH(UPDLOCK,HOLDLOCK) ON x.MachineId=m.MachineId
            WHERE m.MachineId=%s AND m.CustomerId=%s AND m.IsActive=1""", machine_id, self.ctx.customer_id)
        if not machine:
            raise Error(404, "Machine not found")
        if machine["Version"] != integer(body.get("version"), 1, 2**63 - 1, "version"):
            raise Error(409, "Machine settings changed. Refresh and try again.")
        if self.db.one("SELECT TOP(1) EntryId FROM scheduler.Entry WHERE MachineId=%s AND IsOpen=1", machine_id):
            raise Error(409, "The machine still has open tables or tournament registrations. Disable it and let its bots finish first.")
        if self.db.one("SELECT TOP(1) BotAccountId FROM scheduler.AccountLease WHERE MachineId=%s", machine_id):
            raise Error(409, "An account is still logged in on this machine. Disable it and wait until its sessions end.")
        self.db.execute("EXEC backoffice.RetireMachine @CustomerId=%s,@MachineId=%s", self.ctx.customer_id, machine_id)
        self.audit("machine.delete", machine_id, {"name": machine["Name"]})
        return {"deleted": machine_id}

    def overview(self, site_id):
        site = self.site(site_id)
        accounts = self.db.one("""SELECT COUNT(*) AS total,COALESCE(SUM(CASE WHEN p.IsSynthetic=1 THEN 1 ELSE 0 END),0) AS synthetic
            FROM scheduler.AccountPolicy p JOIN dbo.BotAccount b ON b.BotAccountId=p.BotAccountId
            WHERE p.SiteId=%s AND p.DeletedUtc IS NULL""",site_id)
        machines = self.db.rows("""SELECT m.MachineId AS id,COALESCE(x.HostName,m.Description) AS name,
            a.IsReady AS ready,a.LastHeartbeatUtc AS heartbeat,
            averages.AvgCpu AS average_cpu,averages.AvgMemory AS average_memory,averages.AvgDisk AS average_disk
            FROM dbo.CustomerMachine m LEFT JOIN backoffice.MachineMetadata x ON x.MachineId=m.MachineId
            JOIN scheduler.MachineAssignment a ON a.MachineId=m.MachineId AND a.SiteId=%s
            OUTER APPLY(SELECT AVG(CONVERT(float,t.CpuPercent)) AS AvgCpu,
                AVG(CONVERT(float,t.MemoryPercent)) AS AvgMemory,AVG(CONVERT(float,t.DiskPercent)) AS AvgDisk
                FROM scheduler.MachineTelemetry t WHERE t.SiteId=a.SiteId AND t.MachineId=m.MachineId
                    AND t.SampledUtc>=DATEADD(minute,-15,SYSUTCDATETIME())) averages
            WHERE m.CustomerId=%s AND m.IsActive=1 ORDER BY m.MachineId""",site_id,self.ctx.customer_id)
        for machine in machines:machine_health(machine)
        # Ring entries count as seated when the observer confirms the seat. Tournament tables are not
        # observed: a tournament entry is 'seated' once the tournament seated the bot, else 'registered'.
        entries = self.db.rows(f"""SELECT x.format,x.status,COUNT(*) AS count FROM (
            SELECT f.format,CASE WHEN f.format<>'RING' THEN CASE WHEN p.Status='seated' THEN 'seated'
                    WHEN p.Status='joining' THEN 'registered' WHEN p.Status='reserved' THEN 'reserved' ELSE 'uncertain' END
                WHEN p.IsConfirmedSeat=1 THEN 'seated' WHEN p.Status IN ('reserved','joining') THEN p.Status ELSE 'uncertain' END AS status
            FROM backoffice.EntryPresence p {ENTRY_LOBBY_JOIN} CROSS APPLY(SELECT {ENTRY_FORMAT_SQL} AS format) f
            WHERE p.SiteId=%s AND p.IsOpen=1 AND p.IsLiveOwner=1) x GROUP BY x.format,x.status""",site_id)
        zone=ZoneInfo(site["timezone"]);local_now=datetime.now(timezone.utc).astimezone(zone)
        today=datetime.combine(local_now.date(),datetime.min.time(),zone).astimezone(timezone.utc).replace(tzinfo=None)
        month=datetime.combine(local_now.date()-timedelta(days=29),datetime.min.time(),zone).astimezone(timezone.utc).replace(tzinfo=None)
        prefix=f"{self.ctx.customer_id}/{site['name']}/"
        history = self.db.one("""SELECT SUM(CASE WHEN UploadedUtc>=%s THEN 1 ELSE 0 END) AS today,
            SUM(CASE WHEN UploadedUtc>=%s THEN 1 ELSE 0 END) AS last_30_days,MAX(UploadedUtc) AS latest
            FROM dbo.CustomerHandHistory WHERE CustomerId=%s AND LEFT(BlobPath,LEN(%s))=%s""",
            today,month,self.ctx.customer_id,prefix,prefix)
        schedules = self.schedules(site_id)
        schedule = schedules["RING"]
        from .mtts import planned_target
        now = datetime.now(timezone.utc)
        schedules["MTT"] = {**schedules["MTT"], "windows": [], "target": planned_target(self.db, site_id, now, now)}
        online=sum(1 for machine in machines if machine["online"])
        warnings=[{"machine":m["name"] or f"Machine {m['id']}","message":warning}
                  for m in machines for warning in m["warnings"]]
        offline_machines=sorted(({"machine":m["name"] or f"Machine {m['id']}","heartbeat":m["heartbeat"]}
                                 for m in machines if not m["online"]),
                                key=lambda m:(m["heartbeat"] is not None,m["heartbeat"] or datetime.min))
        return {"site": site, "accounts": accounts["total"], "synthetic_accounts": accounts["synthetic"],
                "entries": entries, "targets": {fmt: scheduled_target(s) for fmt, s in schedules.items()},
                "windows": {**{fmt: len(s["windows"]) for fmt, s in schedules.items()},
                            "MTT": self.db.one("SELECT COUNT(*) AS n FROM scheduler.MttPlan WHERE SiteId=%s AND TotalBots>0", site_id)["n"]},
                "machines": machines,
                "machine_summary":{"online":online,"offline":len(machines)-online,"warnings":warnings,
                                   "offline_machines":offline_machines},
                "hand_histories": history, "schedule": schedule}

    def entry_metrics(self, site_id, query):
        """Scheduled target and running entries of one format over a bounded date range.

        RING: confirmed seated entries. SNG/MTT: bots registered in or playing a tournament, the
        quantity the tournament target schedules (from registration until the bot's tournament ends)."""
        site = self.site(site_id)
        fmt = choice(query.get("format") or "RING", FORMATS, "format")
        schedule = self.schedule(site_id, fmt)
        zone = ZoneInfo(site["timezone"])
        local_now = datetime.now(timezone.utc).astimezone(zone)
        try:
            from_day = datetime.strptime(query.get("from") or local_now.date().isoformat(), "%Y-%m-%d").date()
            to_day = datetime.strptime(query.get("to") or local_now.date().isoformat(), "%Y-%m-%d").date()
        except ValueError:
            raise Error(400, "From and To must be valid dates")
        if to_day < from_day:
            raise Error(400, "To date must not be before From date")
        days = (to_day - from_day).days + 1
        if days > 92:
            raise Error(400, "Entry chart range cannot exceed 92 days")
        start = datetime.combine(from_day, datetime.min.time(), zone).astimezone(timezone.utc)
        requested_stop = datetime.combine(to_day + timedelta(days=1), datetime.min.time(), zone).astimezone(timezone.utc)
        stop = min(requested_stop, datetime.now(timezone.utc))
        if stop <= start:
            raise Error(400, "The selected range has not started yet")
        step_minutes = 1 if days <= 2 else 30 if days <= 14 else 120
        if fmt == "MTT":
            from .mtts import planned_target
            schedule = {**schedule, "windows": [], "target": planned_target(self.db, site_id, start, stop)}
        if fmt == "RING":
            rows = self.db.rows(f"""SELECT p.SeatedUtc AS seated,CASE WHEN p.LastConfirmedUtc IS NOT NULL AND (p.ClosedUtc IS NULL OR p.ClosedUtc>DATEADD(second,60,p.LastConfirmedUtc)) THEN DATEADD(second,60,p.LastConfirmedUtc) ELSE p.ClosedUtc END AS closed
                FROM scheduler.Entry p {ENTRY_LOBBY_JOIN} WHERE p.SiteId=%s AND p.SeatedUtc IS NOT NULL AND {ENTRY_FORMAT_SQL}='RING'
                  AND p.SeatedUtc<%s AND (p.ClosedUtc IS NULL OR p.ClosedUtc>%s)""",
                site_id, stop.replace(tzinfo=None), start.replace(tzinfo=None))
        else:
            rows = self.db.rows(f"""SELECT p.CreatedUtc AS seated,p.ClosedUtc AS closed
                FROM scheduler.Entry p {ENTRY_LOBBY_JOIN} WHERE p.SiteId=%s AND p.Status<>'failed' AND {ENTRY_FORMAT_SQL}=%s
                  AND p.CreatedUtc<%s AND (p.ClosedUtc IS NULL OR p.ClosedUtc>%s)""",
                site_id, fmt, stop.replace(tzinfo=None), start.replace(tzinfo=None))
        intervals = [(
            row["seated"].replace(tzinfo=timezone.utc),
            row["closed"].replace(tzinfo=timezone.utc) if row["closed"] else None
        ) for row in rows]
        points = entry_history_points(schedule, intervals, start, stop, step_minutes)
        if requested_stop>=datetime.now(timezone.utc) and points:
            seated = "p.IsConfirmedSeat=1" if fmt == "RING" else "p.IsLiveOwner=1"
            live=self.db.one(f"""SELECT COUNT(*) AS n FROM backoffice.EntryPresence p {ENTRY_LOBBY_JOIN}
                WHERE p.SiteId=%s AND p.IsOpen=1 AND {seated} AND {ENTRY_FORMAT_SQL}=%s""",site_id,fmt)['n']
            points[-1]['running']=live
        return {"format": fmt, "from": from_day.isoformat(), "to": to_day.isoformat(), "timezone": site["timezone"],
                "step_minutes": step_minutes, "points": points}
