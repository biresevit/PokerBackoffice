"""MTT plans (Schedule page, MTT tab): every MTT the lobby lists, grouped by its name without the date, and the
operator's plan for it: total bots, how many rebuy / re-enter and take the add-on, the early-registration share and
how many hours before the start early registration begins. The scheduler reads scheduler.MttPlan every tick."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from schedule_controller.mtt_plans import (DEFAULT_EARLY_HOURS, DEFAULT_EARLY_PERCENT, MttPlan, desired, late_registration,
                                           parse_info, recurrence, registration_window, series_name, split)

from .validation import Error, integer, number

# A lobby row seen this recently is still listed by the site (rows of MTTs that left the lobby are never updated).
FRESH = timedelta(minutes=30)
# Start times this far back still describe how a series recurs.
HISTORY = timedelta(days=8)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def plan_json(row):
    return None if row is None else {"total": row["TotalBots"], "rebuy": row["RebuyBots"], "addon": row["AddonBots"],
                                     "early_percent": row["EarlyPercent"], "early_hours": float(row["EarlyHours"]),
                                     "updated": row["UpdatedUtc"]}


class Mtts:
    def __init__(self, store):
        self.store, self.db, self.ctx = store, store.db, store.ctx

    def overview(self, site_id, query):
        site=self.store.site(site_id)
        zone=ZoneInfo(site['timezone']);now=datetime.now(timezone.utc)
        try:
            first=datetime.strptime(query.get('from') or now.astimezone(zone).date().isoformat(),'%Y-%m-%d').date()
            last=datetime.strptime(query.get('to') or now.astimezone(zone).date().isoformat(),'%Y-%m-%d').date()
        except (ValueError,TypeError):
            raise Error(400,'From and To must be valid dates')
        if last<first:raise Error(400,'To date must not be before From date')
        if (last-first).days>=92:raise Error(400,'MTT overview range cannot exceed 92 days')
        start=datetime.combine(first,datetime.min.time(),zone).astimezone(timezone.utc).replace(tzinfo=None)
        stop=datetime.combine(last+timedelta(days=1),datetime.min.time(),zone).astimezone(timezone.utc).replace(tzinfo=None)
        rows=self.db.rows("""SELECT l.TableId,l.TableName,l.GameType,l.StartUtc,l.TournamentState,
                COUNT(DISTINCT CASE WHEN registration.Confirmed=1 OR e.SeatedUtc IS NOT NULL
                    OR (e.Status<>'failed' AND e.LastConfirmedUtc IS NOT NULL)
                    THEN e.BotAccountId END) AS registered,
                COUNT(DISTINCT CASE WHEN e.SeatedUtc IS NOT NULL THEN e.BotAccountId END) AS ever_seated,
                COUNT(DISTINCT CASE WHEN e.IsOpen=1 AND e.IsLiveOwner=1 AND e.SeatedUtc IS NOT NULL
                    AND e.Status IN ('seated','sitting_out','draining') THEN e.BotAccountId END) AS running
            FROM scheduler.LobbyTable l
            LEFT JOIN backoffice.EntryPresence e ON e.SiteId=l.SiteId AND e.TableId=l.TableId
            OUTER APPLY (SELECT TOP(1) 1 AS Confirmed FROM scheduler.Command c
                WHERE c.EntryId=e.EntryId AND c.Kind='join' AND c.Status='succeeded' AND c.ResultCode IS NULL
                  AND JSON_VALUE(c.PayloadJson,'$.resume_registration') IS NULL) registration
            WHERE l.SiteId=%s AND l.TableType='MTT' AND l.StartUtc>=%s AND l.StartUtc<%s
            GROUP BY l.TableId,l.TableName,l.GameType,l.StartUtc,l.TournamentState
            ORDER BY l.StartUtc,l.TableName,l.TableId""",site_id,start,stop)
        plans={r['SeriesName']:r['TotalBots'] for r in self.db.rows(
            'SELECT SeriesName,TotalBots FROM scheduler.MttPlan WHERE SiteId=%s',site_id)}
        items=[dict(id=r['TableId'],name=r['TableName'],game=r['GameType'],start=utc(r['StartUtc']),
                    state=r['TournamentState'],scheduled=plans.get(series_name(r['TableName'])),
                    registered=r['registered'],running=r['running'],ever_seated=r['ever_seated']) for r in rows]
        return dict(format='MTT',view='tournaments',timezone=site['timezone'],**{'from':first.isoformat(),'to':last.isoformat()},
                    as_of=now,items=items,totals={key:sum(i[key] or 0 for i in items)
                    for key in ('scheduled','registered','running','ever_seated')})

    def list(self, site_id):
        site = self.store.site(site_id)
        now = datetime.now(timezone.utc)
        rows = self.db.rows("""SELECT TableId,TableName,GameType,MinBuyIn,StartUtc,TournamentState,IsOpen,OccupiedSeats,
                MaxSeats,ObservedUtc,TournamentInfo FROM scheduler.LobbyTable
            WHERE SiteId=%s AND TableType='MTT' AND StartUtc>=%s""", site_id, (now - HISTORY).replace(tzinfo=None))
        bots = {r["TableId"]: r for r in self.db.rows("""SELECT e.TableId,
                SUM(CASE WHEN e.IsOpen=1 OR e.SeatedUtc IS NOT NULL THEN 1 ELSE 0 END) AS registered,
                SUM(CASE WHEN e.IsOpen=1 THEN 1 ELSE 0 END) AS open_entries,
                SUM(CASE WHEN e.TournamentRebuy=1 THEN 1 ELSE 0 END) AS rebuy,
                SUM(CASE WHEN e.TournamentAddon=1 THEN 1 ELSE 0 END) AS addon
            FROM scheduler.Entry e JOIN scheduler.LobbyTable l ON l.SiteId=e.SiteId AND l.TableId=e.TableId
            WHERE e.SiteId=%s AND l.TableType='MTT' AND l.StartUtc>=%s AND e.Status<>'failed'
            GROUP BY e.TableId""", site_id, (now - HISTORY).replace(tzinfo=None))}
        plans = {r["SeriesName"]: r for r in self.db.rows("SELECT * FROM scheduler.MttPlan WHERE SiteId=%s", site_id)}
        series = {}
        for r in rows:
            name = series_name(r["TableName"])
            group = series.setdefault(name, {"series": name, "starts": [], "instances": []})
            start, observed = utc(r["StartUtc"]), utc(r["ObservedUtc"])
            group["starts"].append(start)
            listed = r["TournamentState"] != "completed" and observed >= now - FRESH
            if not listed:
                continue
            info = parse_info(r["TournamentInfo"])
            b = bots.get(r["TableId"]) or {}
            group["instances"].append({
                "id": r["TableId"], "name": r["TableName"], "game": r["GameType"], "start": start,
                "state": r["TournamentState"], "open": bool(r["IsOpen"]), "buy_in": r["MinBuyIn"],
                "players": r["OccupiedSeats"], "info": info, "bots": int(b.get("registered") or 0),
                "bots_open": int(b.get("open_entries") or 0), "bots_rebuy": int(b.get("rebuy") or 0),
                "bots_addon": int(b.get("addon") or 0)})
        result = []
        for name, group in series.items():
            if not group["instances"]:
                continue
            group["instances"].sort(key=lambda i: (i["start"], i["id"]))
            plan_row = plans.get(name)
            plan = MttPlan(plan_row["TotalBots"], plan_row["RebuyBots"], plan_row["AddonBots"], plan_row["EarlyPercent"],
                           float(plan_row["EarlyHours"])) if plan_row else None
            for i in group["instances"]:
                if plan and plan.total:
                    early, late = split(plan, late_registration(i["info"]))
                    first, last = registration_window(plan, i["start"], i["info"])
                    i["plan"] = {"target_now": desired(plan, i["start"], now, i["info"]), "early": early, "late": late,
                                 "first": first, "last": last}
            latest = group["instances"][-1]
            result.append({"series": name, "instances": group["instances"], "recurrence": recurrence(group["starts"]),
                           "next_start": group["instances"][0]["start"], "buy_in": latest["buy_in"],
                           "game": latest["game"], "info": latest["info"], "plan": plan_json(plan_row)})
        result.sort(key=lambda s: (s["next_start"], s["series"]))
        # Plans whose MTT is not listed right now (for example a weekly one) are kept and shown too.
        listed = {s["series"] for s in result}
        missing = [{"series": n, "plan": plan_json(r)} for n, r in sorted(plans.items()) if n not in listed]
        return {"timezone": site["timezone"], "currency": site["currency"], "series": result, "unlisted_plans": missing,
                "defaults": {"early_percent": DEFAULT_EARLY_PERCENT, "early_hours": DEFAULT_EARLY_HOURS}}

    def save(self, site_id, body):
        self.store.site(site_id)
        if self.ctx.role != "operator":
            raise Error(403, "Your account has view-only access")
        name = str(body.get("series") or "").strip()
        if not name or len(name) > 200:
            raise Error(400, "Choose an MTT")
        total = integer(body.get("total"), 0, 1000, "Total bots")
        rebuy = integer(body.get("rebuy", 0), 0, 1000, "Bots that rebuy or re-enter")
        addon = integer(body.get("addon", 0), 0, 1000, "Bots that take the add-on")
        if rebuy > total or addon > total:
            raise Error(400, "Rebuy / re-entry and add-on bots cannot be more than the total bots")
        early = integer(body.get("early_percent", DEFAULT_EARLY_PERCENT), 0, 100, "Early registration (%)")
        hours = number(body.get("early_hours", DEFAULT_EARLY_HOURS), 0.25, 72, "Early registration starts (hours before)")
        self.db.execute("""MERGE scheduler.MttPlan WITH(HOLDLOCK) AS p
            USING (SELECT %s AS SiteId,%s AS SeriesName) AS s ON p.SiteId=s.SiteId AND p.SeriesName=s.SeriesName
            WHEN MATCHED THEN UPDATE SET TotalBots=%s,RebuyBots=%s,AddonBots=%s,EarlyPercent=%s,EarlyHours=%s,
                UpdatedUtc=SYSUTCDATETIME(),UpdatedBy=%s
            WHEN NOT MATCHED THEN INSERT(SiteId,SeriesName,TotalBots,RebuyBots,AddonBots,EarlyPercent,EarlyHours,UpdatedBy)
                VALUES(s.SiteId,s.SeriesName,%s,%s,%s,%s,%s,%s);""",
            site_id, name, total, rebuy, addon, early, hours, self.ctx.subject,
            total, rebuy, addon, early, hours, self.ctx.subject)
        values = {"total": total, "rebuy": rebuy, "addon": addon, "early_percent": early, "early_hours": float(hours)}
        self.store.audit("mtt_plan.save", site_id, {"series": name, **values})
        return {"series": name, "plan": values}

    def delete(self, site_id, body):
        self.store.site(site_id)
        if self.ctx.role != "operator":
            raise Error(403, "Your account has view-only access")
        name = str(body.get("series") or "").strip()
        self.db.execute("DELETE scheduler.MttPlan WHERE SiteId=%s AND SeriesName=%s", site_id, name)
        self.store.audit("mtt_plan.delete", site_id, {"series": name})
        return {"series": name, "plan": None}


def planned_target(db, site_id, start, stop):
    """MTT counterpart of a weekly schedule: a function instant -> bots the plans want registered by then, summed
    over the MTT starts whose registrations run at that instant (from the first early to the last late one)."""
    plans = {r["SeriesName"]: MttPlan(r["TotalBots"], r["RebuyBots"], r["AddonBots"], r["EarlyPercent"], float(r["EarlyHours"]))
             for r in db.rows("SELECT * FROM scheduler.MttPlan WHERE SiteId=%s AND TotalBots>0", site_id)}
    if not plans:
        return lambda instant: 0
    rows = db.rows("""SELECT TableName,StartUtc,TournamentInfo FROM scheduler.LobbyTable WHERE SiteId=%s AND TableType='MTT'
        AND StartUtc BETWEEN %s AND %s""", site_id, (start - timedelta(hours=73)).replace(tzinfo=None),
        (stop + timedelta(hours=73)).replace(tzinfo=None))
    starts = []
    for r in rows:
        plan = plans.get(series_name(r["TableName"]))
        if plan is None:
            continue
        info, when = parse_info(r["TournamentInfo"]), utc(r["StartUtc"])
        first, last = registration_window(plan, when, info)
        starts.append((first, last, plan, when, info))

    def target(instant):
        return sum(desired(plan, when, instant, info) for first, last, plan, when, info in starts if first <= instant <= last)
    return target
