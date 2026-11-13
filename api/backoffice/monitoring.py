"""Monitoring page: how long PDecision takes to decide and how often bots miss their turn.

The PC workers write scheduler.DecisionMetric (decision durations summed per PC, hour, street and opponents in the
hand) and scheduler.ActionTimeout (one row per missed action) every 5 minutes. Everything here is per site, so a
customer only sees its own PCs."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .validation import Error, integer

STREETS = {1: "Preflop", 2: "Flop", 3: "Turn", 4: "River"}
BANDS = ("Under250", "Under500", "Under1000", "Under2000", "Under5000", "Over5000")
LIMITS = (250, 500, 1000, 2000, 5000, None)
MAX_DAYS = 31


def parse_time(value, default):
    if not value:
        return default
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise Error(400, "Invalid date") from None
    return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)


def percentile(bands, share):
    """The duration band holding the given share of the decisions: its upper limit in ms (None above 5 s)."""
    total = sum(bands)
    if not total:
        return None
    seen = 0
    for count, limit in zip(bands, LIMITS):
        seen += count
        if seen >= total * share:
            return limit
    return None


def summary(rows):
    decisions = sum(r["decisions"] for r in rows)
    bands = [sum(r[b] for r in rows) for b in BANDS]
    return {"decisions": decisions,
            "avg_ms": round(sum(r["total_ms"] for r in rows) / decisions) if decisions else None,
            "max_ms": max((r["max_ms"] for r in rows), default=None),
            "bands": bands, "p50_under_ms": percentile(bands, .5), "p90_under_ms": percentile(bands, .9),
            "slow_share": round((bands[4] + bands[5]) / decisions, 4) if decisions else None}


class Monitoring:
    def __init__(self, store):
        self.store, self.db = store, store.db

    def get(self, site_id, query):
        self.store.site(site_id)
        now = datetime.now(timezone.utc)
        stop = parse_time(query.get("to"), now)
        start = parse_time(query.get("from"), stop - timedelta(hours=24))
        if start >= stop:
            raise Error(400, "The start must be before the end")
        if stop - start > timedelta(days=MAX_DAYS):
            raise Error(400, f"Choose at most {MAX_DAYS} days")
        machine = query.get("machine") or "all"
        machine = None if machine == "all" else integer(machine, 1, field="machine")
        opponents = query.get("opponents") or "all"
        opponents = None if opponents == "all" else integer(opponents, 1, 9, "opponents")
        machines = {r["id"]: r for r in self.db.rows("""SELECT ma.MachineId AS id,
                COALESCE(x.HostName,cm.Description,CONCAT('PC ',ma.MachineId)) AS name
            FROM scheduler.MachineAssignment ma JOIN dbo.CustomerMachine cm ON cm.MachineId=ma.MachineId
            LEFT JOIN backoffice.MachineMetadata x ON x.MachineId=ma.MachineId
            WHERE ma.SiteId=%s AND cm.CustomerId=%s""", site_id, self.store.ctx.customer_id)}
        if machine is not None and machine not in machines:
            raise Error(404, "Machine not found")
        # Rows are hourly: an hour counts when it starts inside the range.
        hour_from = start.replace(minute=0, second=0, microsecond=0)
        where, args = ["SiteId=%s", "HourUtc>=%s", "HourUtc<%s"], [site_id, hour_from.replace(tzinfo=None), stop.replace(tzinfo=None)]
        if machine is not None:
            where.append("MachineId=%s"); args.append(machine)
        if opponents is not None:
            where.append("Opponents>=%s" if opponents >= 5 else "Opponents=%s"); args.append(opponents)
        rows = self.db.rows(f"""SELECT MachineId AS machine,HourUtc AS hour,Street AS street,
                SUM(Decisions) AS decisions,SUM(TotalMs) AS total_ms,MAX(MaxMs) AS max_ms,
                {",".join(f"SUM({b}) AS {b}" for b in BANDS)}
            FROM scheduler.DecisionMetric WHERE {" AND ".join(where)}
            GROUP BY MachineId,HourUtc,Street""", *args)
        twhere, targs = ["t.SiteId=%s", "t.OccurredUtc>=%s", "t.OccurredUtc<%s"], [site_id, start.replace(tzinfo=None), stop.replace(tzinfo=None)]
        if machine is not None:
            twhere.append("t.MachineId=%s"); targs.append(machine)
        timeouts = self.db.rows(f"""SELECT t.MachineId AS machine,t.Kind AS kind,t.OccurredUtc AS at,
                COALESCE(b.Username,t.Username) AS username,t.TableId AS table_id,l.TableName AS table_name
            FROM scheduler.ActionTimeout t LEFT JOIN dbo.BotAccount b ON b.BotAccountId=t.BotAccountId
            LEFT JOIN scheduler.LobbyTable l ON l.SiteId=t.SiteId AND l.TableId=t.TableId
            WHERE {" AND ".join(twhere)} ORDER BY t.OccurredUtc DESC""", *targs)
        hours = {}
        for r in rows:
            hours.setdefault(r["hour"], []).append(r)
        missed_by_hour = {}
        for t in timeouts:
            missed_by_hour.setdefault(t["at"].replace(minute=0, second=0, microsecond=0), []).append(t)
        series = []
        for hour in sorted(set(hours) | set(missed_by_hour)):
            s = summary(hours.get(hour, []))
            series.append({"at": hour.replace(tzinfo=timezone.utc), "decisions": s["decisions"], "avg_ms": s["avg_ms"],
                           "max_ms": s["max_ms"], "missed": len(missed_by_hour.get(hour, []))})
        per_machine = []
        for mid in sorted({r["machine"] for r in rows} | {t["machine"] for t in timeouts}):
            mine = [t for t in timeouts if t["machine"] == mid]
            per_machine.append({"id": mid, "name": (machines.get(mid) or {}).get("name") or f"PC {mid}",
                                **summary([r for r in rows if r["machine"] == mid]),
                                "sit_out": sum(t["kind"] == "sit_out" for t in mine),
                                "clock_acted": sum(t["kind"] == "clock_acted" for t in mine)})
        return {
            "from": start, "to": stop, "timezone": self.store.site(site_id)["timezone"],
            "machines": [{"id": m["id"], "name": m["name"]} for m in sorted(machines.values(), key=lambda m: m["name"])],
            "overall": summary(rows),
            "streets": [{"street": s, "name": n, **summary([r for r in rows if r["street"] == s])} for s, n in STREETS.items()],
            "per_machine": per_machine, "series": series,
            "missed": {"total": len(timeouts), "sit_out": sum(t["kind"] == "sit_out" for t in timeouts),
                       "clock_acted": sum(t["kind"] == "clock_acted" for t in timeouts),
                       "recent": [{**t, "at": t["at"].replace(tzinfo=timezone.utc),
                                   "machine_name": (machines.get(t["machine"]) or {}).get("name")} for t in timeouts[:200]]},
        }
