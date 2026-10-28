from __future__ import annotations

import hashlib
import json
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .validation import Error, PROFILES, TIERS, integer, username, windows, stake_bands, account_settings, parse_csv


def scheduled_target(schedule, instant=None):
    """Target entries for an instant, using the site's local weekday/time."""
    if not schedule["enabled"]:
        return 0
    local = (instant or datetime.now(timezone.utc)).astimezone(ZoneInfo(schedule["timezone"]))
    minute = local.hour * 60 + local.minute
    return next((row["target"] for row in schedule["windows"]
                 if row["weekday"] == local.weekday()
                 and row["start_minute"] <= minute < row["end_minute"]), 0)


def live_table_sort_key(row):
    """Ring formats first; tournaments follow, retaining occupancy priority per group."""
    table_type = str(row.get("table_type") or "RING").upper()
    game = str(row.get("game") or "").upper()
    if table_type == "RING":
        group = {"NLH": 0, "PLO4": 1, "PLO5": 2}.get(game, 5)
    else:
        group = {"SNG": 3, "MTT": 4}.get(table_type, 5)
    return (group,
            0 if row["bot_entries"] else 1 if row["occupied"] else 2,
            -row["bot_entries"], -row["occupied"], row["big_blind"], row["name"])


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

    def sites(self):
        return self.db.rows("""SELECT SiteId AS id,Casino AS name,Platform AS platform,TimeZone AS timezone,
            CurrencyCode AS currency,SchedulingEnabled AS enabled,ConfigVersion AS version
            FROM scheduler.Site WHERE CustomerId=%s ORDER BY Casino""", self.ctx.customer_id)

    def site(self, site_id, *, lock=False, version=None):
        hint = "WITH(UPDLOCK,HOLDLOCK)" if lock else ""
        result = self.db.one(f"""SELECT SiteId AS id,Casino AS name,CustomerId AS customer_id,TimeZone AS timezone,
            CurrencyCode AS currency,ConfigVersion AS version,SchedulingEnabled AS enabled
            FROM scheduler.Site {hint} WHERE SiteId=%s AND CustomerId=%s""", site_id, self.ctx.customer_id)
        if result is None:
            raise Error(404, "Site not found")
        if lock:
            if self.ctx.role != "operator":
                raise Error(403, "Your account has view-only access")
            if integer(version, 1, 2**63 - 1, "configuration version") != result["version"]:
                raise Error(409, "Settings changed since this page was loaded. Refresh and try again.")
        return result

    def bump(self, site_id):
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
            p.SessionMinMinutes AS session_min_minutes,p.SessionMaxMinutes AS session_max_minutes,
            p.SessionCooldownMinutes AS session_cooldown_minutes,
            p.PostBbChance AS post_bb_chance,p.RunItTwiceChance AS run_it_twice_chance,
            p.BuyInPolicyJson AS buy_in_json,p.IsSynthetic AS synthetic,p.IsEnabled AS enabled,
            COALESCE(d.SessionSeconds,0) AS played_seconds,
            (SELECT COUNT(*) FROM scheduler.Entry e WHERE e.SiteId=p.SiteId AND e.BotAccountId=p.BotAccountId AND e.IsOpen=1) AS entries
            FROM scheduler.AccountPolicy p JOIN dbo.BotAccount b ON b.BotAccountId=p.BotAccountId
            LEFT JOIN scheduler.AccountDay d ON d.SiteId=p.SiteId AND d.BotAccountId=p.BotAccountId AND d.LocalDate=%s
            WHERE p.SiteId=%s AND p.DeletedUtc IS NULL ORDER BY b.Username""", today, site_id)
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
        self.db.execute("UPDATE dbo.BotAccount SET Strategy=%s,UpdatedUtc=SYSUTCDATETIME() WHERE BotAccountId=%s",
                        values["strategy"], account_id)
        self.db.execute("""UPDATE scheduler.AccountPolicy SET StakeTier=%s,PlayingFrequency=%s,
            MaxPlaytimeMinutes=%s,MaxTables=%s,PostBbChance=%s,RunItTwiceChance=%s,BuyInPolicyJson=%s,
            UpdatedUtc=SYSUTCDATETIME() WHERE SiteId=%s AND BotAccountId=%s""",
            values["stake"], values["frequency"], values["max_minutes"], values["max_tables"],
            values["post_bb_chance"], values["run_it_twice_chance"], json.dumps(values["buy_in_weights"]), site_id, account_id)
        if enabled is not None:
            self.db.execute("UPDATE scheduler.AccountPolicy SET IsEnabled=%s WHERE SiteId=%s AND BotAccountId=%s", enabled, site_id, account_id)
        if durations:
            self.db.execute("UPDATE scheduler.AccountPolicy SET SessionMinMinutes=%s,SessionMaxMinutes=%s,SessionCooldownMinutes=%s WHERE SiteId=%s AND BotAccountId=%s", *durations, site_id, account_id)
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
                {"20": 5, "30": 5, "40": 5, "100": 65, "200": 20} if strong else
                {"20": 6.25, "30": 6.25, "40": 6.25, "50": 6.25, "100": 55, "200": 15, "irregular": 5})

    def _import_plan(self, site_id, site, rows, mode):
        if mode not in ("upsert", "replace"):
            raise Error(400, "Invalid import mode")
        existing = self.db.rows("""SELECT b.BotAccountId AS id,b.Username AS username,b.Strategy AS strategy,
            p.SiteId AS site_id,p.DeletedUtc AS deleted,p.IsSynthetic AS synthetic
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
                raise Error(409, f"Account {row['username']} requires an administrator ownership assignment")
            kind = "create" if not old else "restore" if old["deleted"] else "update" if row["strategy"] != old["strategy"] else "unchanged"
            changes.append(dict(row, kind=kind, id=old["id"] if old else None))
        if mode == "replace":
            for old in existing:
                if old["site_id"] == site_id and not old["deleted"] and old["username"].casefold() not in wanted:
                    self._ensure_idle(site_id, old["id"])
                    changes.append({"id": old["id"], "username": old["username"], "strategy": old["strategy"], "kind": "delete"})
        token = hashlib.sha256(json.dumps([site_id, site["version"], mode, changes], sort_keys=True).encode()).hexdigest()
        return {"changes": changes, "token": token,
                "counts": {k: sum(r["kind"] == k for r in changes) for k in ("create", "update", "restore", "delete", "unchanged")},
                "version": site["version"]}

    def import_accounts(self, site_id, body, *, apply=False):
        site = self.site(site_id, lock=apply, version=body.get("version"))
        if self.ctx.role != "operator":
            raise Error(403, "Your account has view-only access")
        rows = parse_csv(body.get("csv"))
        preview = self._import_plan(site_id, site, rows, body.get("mode", "upsert"))
        if not apply:
            return preview
        if body.get("token") != preview["token"]:
            raise Error(409, "Import preview changed. Preview the CSV again before applying it.")
        for change in preview["changes"]:
            kind, aid = change["kind"], change["id"]
            if kind == "create":
                aid = self.db.one("""INSERT dbo.BotAccount(Casino,Username,Strategy) OUTPUT inserted.BotAccountId AS id
                    VALUES(%s,%s,%s)""", site["name"], change["username"], change["strategy"])["id"]
                tier, freq, minutes, post, rit, weights = self._defaults(site_id, change["strategy"])
                self.db.execute("""INSERT scheduler.AccountPolicy(BotAccountId,SiteId,StakeTier,PlayingFrequency,
                    MaxPlaytimeMinutes,PostBbChance,RunItTwiceChance,BuyInPolicyJson)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""", aid, site_id, tier, freq, minutes, post, rit, json.dumps(weights))
            elif kind == "update":
                self.db.execute("UPDATE dbo.BotAccount SET Strategy=%s,UpdatedUtc=SYSUTCDATETIME() WHERE BotAccountId=%s", change["strategy"], aid)
            elif kind == "restore":
                self.db.execute("UPDATE scheduler.AccountPolicy SET DeletedUtc=NULL,UpdatedUtc=SYSUTCDATETIME() WHERE SiteId=%s AND BotAccountId=%s", site_id, aid)
                self.db.execute("""UPDATE b SET Strategy=%s,IsActive=CASE WHEN p.IsSynthetic=1 THEN 0 ELSE 1 END,
                    b.UpdatedUtc=SYSUTCDATETIME() FROM dbo.BotAccount b JOIN scheduler.AccountPolicy p ON p.BotAccountId=b.BotAccountId
                    WHERE p.SiteId=%s AND b.BotAccountId=%s""", change["strategy"], site_id, aid)
            elif kind == "delete":
                self._delete_account(site_id, aid)
        self.bump(site_id)
        self.audit("accounts.import", site_id, {"mode": body.get("mode", "upsert"), "counts": preview["counts"]})
        return {"counts": preview["counts"], "version": site["version"] + 1}

    def schedule(self, site_id):
        site = self.site(site_id)
        rows = self.db.rows("""SELECT Weekday AS weekday,StartMinute AS start_minute,EndMinute AS end_minute,
            TargetEntries AS target FROM scheduler.ScheduleWindow WHERE SiteId=%s ORDER BY Weekday,StartMinute""", site_id)
        return {"windows": rows, "timezone": site["timezone"], "version": site["version"], "enabled": site["enabled"]}

    def save_schedule(self, site_id, body):
        site = self.site(site_id, lock=True, version=body.get("version"))
        values = windows(body)
        zone = str(body.get("timezone", site["timezone"]))
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError):
            raise Error(400, "Unknown IANA timezone")
        self.db.execute("UPDATE scheduler.Site SET TimeZone=%s WHERE SiteId=%s", zone, site_id)
        self.db.execute("EXEC scheduler.SetSchedule @SiteId=%s,@WindowsJson=%s", site_id, json.dumps(values))
        self.audit("schedule.update", site_id, {"timezone": zone, "windows": values})
        return {"version": site["version"] + 1}

    def stakes(self, site_id):
        site = self.site(site_id)
        rows = self.db.rows("""SELECT Tier AS tier,MinBigBlind AS minimum,MaxBigBlind AS maximum,
            UpperInclusive AS upper_inclusive,TargetBasisPoints/100.0 AS [percent]
            FROM scheduler.StakeBand WHERE SiteId=%s ORDER BY MinBigBlind""", site_id)
        return {"bands": rows, "currency": site["currency"], "version": site["version"]}

    def save_stakes(self, site_id, body):
        site = self.site(site_id, lock=True, version=body.get("version"))
        bands = stake_bands(body)
        for b in bands:
            self.db.execute("""UPDATE scheduler.StakeBand SET MinBigBlind=%s,MaxBigBlind=%s,UpperInclusive=%s,
                TargetBasisPoints=%s WHERE SiteId=%s AND Tier=%s""", b["minimum"], b["maximum"], b["upper_inclusive"], b["basis_points"], site_id, b["tier"])
        self.bump(site_id)
        self.audit("stakes.update", site_id, bands)
        return {"version": site["version"] + 1}

    def tables(self, site_id):
        self.site(site_id)
        rows = self.db.rows("""SELECT t.TableId AS id,t.TableName AS name,t.GameType AS game,t.TableType AS table_type,t.BigBlind AS big_blind,
            t.CurrencyCode AS currency,t.MaxSeats AS seats,t.OccupiedSeats AS occupied,t.ObservedUtc AS observed,
            t.FullSnapshotUtc AS snapshot,t.IsOpen AS is_open
            FROM scheduler.LobbyTable t
            WHERE t.SiteId=%s
              AND t.ObservedUtc >= DATEADD(SECOND,-60,SYSUTCDATETIME())
            ORDER BY t.BigBlind,t.TableName""", site_id)
        for row in rows:
            row["players"] = self.db.rows("""SELECT s.SeatIndex AS seat,s.Username AS username,s.Stack AS stack,
                s.CurrentBet AS bet,s.InGame AS in_game,s.SittingOut AS sitting_out,s.BotAccountId AS account_id,
                (SELECT TOP(1) e.MachineId FROM scheduler.Entry e WHERE e.SiteId=s.SiteId AND e.TableId=s.TableId
                 AND e.BotAccountId=s.BotAccountId AND e.IsOpen=1) AS machine_id
                FROM scheduler.TableSeat s WHERE s.SiteId=%s AND s.TableId=%s ORDER BY s.SeatIndex""", site_id, row["id"])
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
        return row

    def machines(self, site_id):
        self.site(site_id)
        rows = self.db.rows("""SELECT m.MachineId AS id,COALESCE(x.HostName,m.Description) AS name,
            m.Casino AS registered_site,x.PublicIp AS public_ip,x.PrivateIp AS private_ip,
            a.MaxEntries AS max_entries,a.IsReady AS ready,a.IsEnabled AS enabled,a.LastHeartbeatUtc AS heartbeat,
            a.SiteId AS active_site_id,COALESCE(x.Version,1) AS version,
            latest.SampledUtc AS telemetry_at,latest.CpuPercent AS cpu_percent,
            latest.MemoryPercent AS memory_percent,latest.DiskPercent AS disk_percent,
            latest.DiskFreeBytes AS disk_free_bytes,latest.DiskTotalBytes AS disk_total_bytes,
            averages.AvgCpu AS average_cpu,averages.AvgMemory AS average_memory,
            averages.AvgDisk AS average_disk,
            (SELECT COUNT(*) FROM scheduler.Entry e JOIN scheduler.Site s ON s.SiteId=e.SiteId
             WHERE e.MachineId=m.MachineId AND s.CustomerId=m.CustomerId AND e.IsOpen=1) AS entries
            FROM dbo.CustomerMachine m LEFT JOIN backoffice.MachineMetadata x ON x.MachineId=m.MachineId
            LEFT JOIN scheduler.MachineAssignment a ON a.MachineId=m.MachineId
            OUTER APPLY (SELECT TOP(1) t.SampledUtc,t.CpuPercent,t.MemoryPercent,t.DiskPercent,
                t.DiskFreeBytes,t.DiskTotalBytes FROM scheduler.MachineTelemetry t
                WHERE t.SiteId=a.SiteId AND t.MachineId=m.MachineId ORDER BY t.SampledUtc DESC) latest
            OUTER APPLY (SELECT AVG(CONVERT(float,t.CpuPercent)) AS AvgCpu,
                AVG(CONVERT(float,t.MemoryPercent)) AS AvgMemory,AVG(CONVERT(float,t.DiskPercent)) AS AvgDisk
                FROM scheduler.MachineTelemetry t WHERE t.SiteId=a.SiteId AND t.MachineId=m.MachineId
                AND t.SampledUtc>=DATEADD(minute,-15,SYSUTCDATETIME())) averages
            WHERE m.CustomerId=%s AND m.IsActive=1 ORDER BY m.MachineId""", self.ctx.customer_id)
        for row in rows:
            row["allowed_sites"] = [r["SiteId"] for r in self.db.rows("SELECT SiteId FROM backoffice.MachineAllowedSite WHERE MachineId=%s", row["id"])]
            heartbeat=row.get("heartbeat")
            row["online"] = bool(row.get("ready") and heartbeat and
                heartbeat >= datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=180))
            warnings=[]
            if row.get("average_cpu") is not None and row["average_cpu"]>=90: warnings.append("CPU has averaged at least 90% for 15 minutes")
            if row.get("average_memory") is not None and row["average_memory"]>=90: warnings.append("Memory usage has averaged at least 90% for 15 minutes")
            if row.get("average_disk") is not None and row["average_disk"]>=90: warnings.append("Disk has less than 10% free space")
            row["warnings"]=warnings
        return {"items": rows, "sites": self.sites()}

    def tasks(self,site_id,query):
        self.site(site_id)
        machine=str(query.get("machine") or "").strip()[:100]
        bot=str(query.get("bot") or "").strip()[:100]
        kind=str(query.get("kind") or "all").lower()
        if kind not in ("all","join","leave","scan"):
            raise Error(400,"Invalid task type")
        page=integer(query.get("page",1),1,100000,"page")
        size=integer(query.get("page_size",50),10,100,"page size")
        if size not in (10,20,50,100): raise Error(400,"Page size must be 10, 20, 50 or 100")
        pattern=lambda value: "%"+value+"%"
        where="""c.SiteId=%s AND (%s='' OR CONVERT(nvarchar(20),c.MachineId)=%s OR
            COALESCE(x.HostName,m.Description,'') LIKE %s) AND (%s='' OR b.Username LIKE %s)
            AND (%s='all' OR c.Kind=%s)"""
        args=(site_id,machine,machine,pattern(machine),bot,pattern(bot),kind,kind)
        total=self.db.one(f"""SELECT COUNT(*) AS n FROM scheduler.Command c
            JOIN scheduler.Entry e ON e.EntryId=c.EntryId JOIN dbo.BotAccount b ON b.BotAccountId=e.BotAccountId
            JOIN dbo.CustomerMachine m ON m.MachineId=c.MachineId
            LEFT JOIN backoffice.MachineMetadata x ON x.MachineId=m.MachineId WHERE {where}""",*args)["n"]
        items=self.db.rows(f"""SELECT c.CommandId AS id,c.Kind AS kind,c.Status AS status,
            c.CreatedUtc AS created,c.UpdatedUtc AS updated,c.NotBeforeUtc AS due,c.AttemptCount AS attempts,
            c.ResultCode AS result_code,c.ResultText AS result_text,e.TableId AS table_id,
            b.Username AS bot,c.MachineId AS machine_id,COALESCE(x.HostName,m.Description) AS machine
            FROM scheduler.Command c JOIN scheduler.Entry e ON e.EntryId=c.EntryId
            JOIN dbo.BotAccount b ON b.BotAccountId=e.BotAccountId
            JOIN dbo.CustomerMachine m ON m.MachineId=c.MachineId
            LEFT JOIN backoffice.MachineMetadata x ON x.MachineId=m.MachineId
            WHERE {where} ORDER BY c.CreatedUtc DESC,c.CommandId
            OFFSET %s ROWS FETCH NEXT %s ROWS ONLY""",*args,(page-1)*size,size)
        choices=self.db.rows("""SELECT DISTINCT c.MachineId AS machine_id,COALESCE(x.HostName,m.Description) AS machine
            FROM scheduler.Command c JOIN dbo.CustomerMachine m ON m.MachineId=c.MachineId
            LEFT JOIN backoffice.MachineMetadata x ON x.MachineId=m.MachineId
            WHERE c.SiteId=%s ORDER BY machine""",site_id)
        bots=self.db.rows("""SELECT b.Username AS username FROM scheduler.AccountPolicy p
            JOIN dbo.BotAccount b ON b.BotAccountId=p.BotAccountId WHERE p.SiteId=%s ORDER BY b.Username""",site_id)
        return {"items":items,"total":total,"page":page,"page_size":size,"machines":choices,"bots":bots}

    def sessions(self,site_id,query):
        site=self.site(site_id)
        zone=ZoneInfo(site["timezone"]);today=datetime.now(timezone.utc).astimezone(zone).date()
        try:
            from_day=datetime.strptime(query.get("from") or (today-timedelta(days=7)).isoformat(),"%Y-%m-%d").date()
            to_day=datetime.strptime(query.get("to") or today.isoformat(),"%Y-%m-%d").date()
        except ValueError: raise Error(400,"From and To must be valid dates")
        if to_day<from_day or (to_day-from_day).days>366: raise Error(400,"Session date range must be between 1 and 367 days")
        start=datetime.combine(from_day,datetime.min.time(),zone).astimezone(timezone.utc).replace(tzinfo=None)
        stop=datetime.combine(to_day+timedelta(days=1),datetime.min.time(),zone).astimezone(timezone.utc).replace(tzinfo=None)
        bot=str(query.get("bot") or "").strip()[:100]
        page=integer(query.get("page",1),1,100000,"page");size=integer(query.get("page_size",50),10,100,"page size")
        if size not in (10,20,50,100): raise Error(400,"Page size must be 10, 20, 50 or 100")
        where="s.SiteId=%s AND s.StartedUtc<%s AND COALESCE(s.ActualEndUtc,SYSUTCDATETIME())>=%s AND (%s='' OR b.Username LIKE %s)"
        args=(site_id,stop,start,bot,"%"+bot+"%")
        total=self.db.one(f"""SELECT COUNT(*) AS n FROM scheduler.AccountSession s
            JOIN dbo.BotAccount b ON b.BotAccountId=s.BotAccountId WHERE {where}""",*args)["n"]
        items=self.db.rows(f"""SELECT s.SessionId AS id,b.Username AS bot,s.MachineId AS machine_id,
            COALESCE(x.HostName,m.Description) AS machine,s.StartedUtc AS started,s.PlannedEndUtc AS planned_end,
            s.ActualEndUtc AS actual_end,s.IsOpen AS is_open,s.EndReason AS end_reason,
            DATEDIFF(second,s.StartedUtc,COALESCE(s.ActualEndUtc,SYSUTCDATETIME())) AS duration_seconds,
            (SELECT COUNT(*) FROM scheduler.Entry e WHERE e.SessionId=s.SessionId) AS entries
            FROM scheduler.AccountSession s JOIN dbo.BotAccount b ON b.BotAccountId=s.BotAccountId
            JOIN dbo.CustomerMachine m ON m.MachineId=s.MachineId
            LEFT JOIN backoffice.MachineMetadata x ON x.MachineId=m.MachineId
            WHERE {where} ORDER BY s.StartedUtc DESC,s.SessionId
            OFFSET %s ROWS FETCH NEXT %s ROWS ONLY""",*args,(page-1)*size,size)
        bots=self.db.rows("""SELECT b.Username AS username FROM scheduler.AccountPolicy p
            JOIN dbo.BotAccount b ON b.BotAccountId=p.BotAccountId WHERE p.SiteId=%s ORDER BY b.Username""",site_id)
        return {"items":items,"total":total,"page":page,"page_size":size,"bots":bots,
                "from":from_day.isoformat(),"to":to_day.isoformat()}

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
        cap = integer(body.get("max_entries"), 1, 10000, "maximum entries")
        allowed = body.get("allowed_sites")
        if not isinstance(allowed, list) or len(allowed) > 100:
            raise Error(400, "Invalid allowed sites")
        allowed = sorted({integer(v, 1, field="site") for v in allowed})
        for sid in allowed:
            self.site(sid)
        active = self.db.rows("SELECT DISTINCT SiteId FROM scheduler.Entry WHERE MachineId=%s AND IsOpen=1", machine_id)
        if any(r["SiteId"] not in allowed for r in active):
            raise Error(409, "Leave active tables before removing their site from this machine")
        self.db.execute("DELETE backoffice.MachineAllowedSite WHERE MachineId=%s", machine_id)
        for sid in allowed:
            self.db.execute("INSERT backoffice.MachineAllowedSite(MachineId,SiteId) VALUES(%s,%s)", machine_id, sid)
        self.db.execute("UPDATE scheduler.MachineAssignment SET MaxEntries=%s WHERE MachineId=%s", cap, machine_id)
        self.db.execute("UPDATE backoffice.MachineMetadata SET Version=Version+1 WHERE MachineId=%s", machine_id)
        self.audit("machine.update", machine_id, {"max_entries": cap, "allowed_sites": allowed})
        return {"version": machine["Version"] + 1}

    def overview(self, site_id):
        site = self.site(site_id)
        accounts = self.accounts(site_id)["items"]
        machines = self.machines(site_id)["items"]
        entries = self.db.rows("SELECT Status AS status,COUNT(*) AS count FROM scheduler.Entry WHERE SiteId=%s AND IsOpen=1 GROUP BY Status", site_id)
        zone=ZoneInfo(site["timezone"]);local_now=datetime.now(timezone.utc).astimezone(zone)
        today=datetime.combine(local_now.date(),datetime.min.time(),zone).astimezone(timezone.utc).replace(tzinfo=None)
        month=datetime.combine(local_now.date()-timedelta(days=29),datetime.min.time(),zone).astimezone(timezone.utc).replace(tzinfo=None)
        prefix=f"{self.ctx.customer_id}/{site['name']}/"
        history = self.db.one("""SELECT SUM(CASE WHEN UploadedUtc>=%s THEN 1 ELSE 0 END) AS today,
            SUM(CASE WHEN UploadedUtc>=%s THEN 1 ELSE 0 END) AS last_30_days,MAX(UploadedUtc) AS latest
            FROM dbo.CustomerHandHistory WHERE CustomerId=%s AND LEFT(BlobPath,LEN(%s))=%s""",
            today,month,self.ctx.customer_id,prefix,prefix)
        schedule = self.schedule(site_id)
        online=sum(1 for machine in machines if machine["online"])
        warnings=[{"machine":m["name"] or f"Machine {m['id']}","message":warning}
                  for m in machines for warning in m["warnings"]]
        return {"site": site, "accounts": len(accounts), "synthetic_accounts": sum(bool(a["synthetic"]) for a in accounts),
                "entries": entries, "scheduled_target": scheduled_target(schedule), "machines": machines,
                "machine_summary":{"online":online,"offline":len(machines)-online,"warnings":warnings},
                "hand_histories": history, "schedule": schedule}

    def entry_metrics(self, site_id, query):
        """Scheduled target and confirmed running entries over a bounded date range."""
        site = self.site(site_id)
        schedule = self.schedule(site_id)
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
        step_minutes = 5 if days <= 2 else 30 if days <= 14 else 120
        rows = self.db.rows("""SELECT SeatedUtc AS seated,ClosedUtc AS closed
            FROM scheduler.Entry WHERE SiteId=%s AND SeatedUtc IS NOT NULL
              AND SeatedUtc<%s AND (ClosedUtc IS NULL OR ClosedUtc>%s)""",
            site_id, stop.replace(tzinfo=None), start.replace(tzinfo=None))
        intervals = [(
            row["seated"].replace(tzinfo=timezone.utc),
            row["closed"].replace(tzinfo=timezone.utc) if row["closed"] else None
        ) for row in rows]
        points = []
        stamp = start
        step = timedelta(minutes=step_minutes)
        while stamp < stop:
            points.append({"at": stamp, "scheduled": scheduled_target(schedule, stamp),
                           "running": sum(seated <= stamp and (closed is None or stamp < closed)
                                          for seated, closed in intervals)})
            stamp += step
        if not points or points[-1]["at"] < stop:
            points.append({"at": stop, "scheduled": scheduled_target(schedule, stop),
                           "running": sum(seated <= stop and (closed is None or stop < closed)
                                          for seated, closed in intervals)})
        return {"from": from_day.isoformat(), "to": to_day.isoformat(), "timezone": site["timezone"],
                "step_minutes": step_minutes, "points": points}
