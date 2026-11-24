"""Monitoring page: how long PDecision takes to decide and how often bots miss their turn.

The PC workers write scheduler.DecisionMetric (decision durations summed per PC, hour, street and opponents in the
hand) and scheduler.ActionTimeout (one row per missed action) every 5 minutes. Everything here is per site, so a
customer only sees its own PCs."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
        site = self.store.site(site_id)
        page_size = integer(query.get('page_size', 20), 20, 100, 'rows')
        if page_size not in (20, 50, 100):
            raise Error(400, 'Choose 20, 50 or 100 rows')
        page = integer(query.get('page', 1), 1, field='page')
        try:
            zone = ZoneInfo(query.get('timezone') or site['timezone'])
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            raise Error(400, 'Invalid timezone') from None
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
        # Aggregate counts independently of the detail page. UTC minute buckets
        # also preserve local-day boundaries in half/quarter-hour timezones.
        bucket = 'DATEADD(minute,DATEDIFF(minute,0,t.OccurredUtc),0)'
        counts = self.db.rows(f"""SELECT t.MachineId AS machine,t.Kind AS kind,
                {bucket} AS at,COUNT_BIG(*) AS count
            FROM scheduler.ActionTimeout t WHERE {" AND ".join(twhere)}
            GROUP BY t.MachineId,t.Kind,{bucket}""", *targs)
        total = sum(r['count'] for r in counts)
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, pages)
        timeouts = self.db.rows(f"""SELECT t.MachineId AS machine,t.Kind AS kind,t.OccurredUtc AS at,
                COALESCE(b.Username,t.Username) AS username,t.TableId AS table_id,l.TableName AS table_name
            FROM scheduler.ActionTimeout t LEFT JOIN dbo.BotAccount b ON b.BotAccountId=t.BotAccountId
            LEFT JOIN scheduler.LobbyTable l ON l.SiteId=t.SiteId AND l.TableId=t.TableId
            WHERE {" AND ".join(twhere)} ORDER BY t.OccurredUtc DESC,t.TimeoutId DESC
            OFFSET %s ROWS FETCH NEXT %s ROWS ONLY""", *targs, (page-1)*page_size, page_size)
        hours = {}
        for r in rows:
            hours.setdefault(r["hour"], []).append(r)
        missed_by_hour = {}
        day = start.astimezone(zone).date()
        last_day = (stop-timedelta(microseconds=1)).astimezone(zone).date()
        daily = {}
        while day <= last_day:
            daily[day.isoformat()] = 0
            day += timedelta(days=1)
        for t in counts:
            hour = t['at'].replace(minute=0, second=0, microsecond=0)
            missed_by_hour[hour] = missed_by_hour.get(hour, 0) + t['count']
            day = t['at'].replace(tzinfo=timezone.utc).astimezone(zone).date().isoformat()
            daily[day] = daily.get(day, 0) + t['count']
        series, by_street = [], {n: [] for n in STREETS}
        for hour in sorted(set(hours) | set(missed_by_hour)):
            s = summary(hours.get(hour, []))
            at = hour.replace(tzinfo=timezone.utc)
            series.append({"at": at, "decisions": s["decisions"], "avg_ms": s["avg_ms"],
                           "max_ms": s["max_ms"], "missed": missed_by_hour.get(hour, 0)})
            for street in STREETS:
                one = summary([r for r in hours.get(hour, []) if r["street"] == street])
                if one["decisions"]:
                    by_street[street].append({"at": at, "decisions": one["decisions"], "avg_ms": one["avg_ms"],
                                              "max_ms": one["max_ms"], "p90_under_ms": one["p90_under_ms"]})
        per_machine = []
        for mid in sorted({r["machine"] for r in rows} | {t["machine"] for t in counts}):
            mine = [t for t in counts if t["machine"] == mid]
            per_machine.append({"id": mid, "name": (machines.get(mid) or {}).get("name") or f"PC {mid}",
                                **summary([r for r in rows if r["machine"] == mid]),
                                "sit_out": sum(t['count'] for t in mine if t["kind"] == "sit_out"),
                                "clock_acted": sum(t['count'] for t in mine if t["kind"] == "clock_acted")})
        from .human_seats import history as human_history
        humans = human_history(self.db, site_id, start, stop, machine=machine)
        return {
            "human_seats": humans,
            "from": start, "to": stop, "timezone": zone.key,
            "machines": [{"id": m["id"], "name": m["name"]} for m in sorted(machines.values(), key=lambda m: m["name"])],
            "overall": summary(rows),
            "streets": [{"street": s, "name": n, **summary([r for r in rows if r["street"] == s])} for s, n in STREETS.items()],
            "per_machine": per_machine, "series": series,
            "series_by_street": [{"street": n, "name": STREETS[n], "points": by_street[n]} for n in STREETS],
            "missed_daily": [{'date': day, 'missed': count} for day, count in sorted(daily.items())],
            "missed": {"total": total, "sit_out": sum(t['count'] for t in counts if t["kind"] == "sit_out"),
                       "clock_acted": sum(t['count'] for t in counts if t["kind"] == "clock_acted"),
                       "page": page, "page_size": page_size, "total_pages": pages,
                       "recent": [{**t, "at": t["at"].replace(tzinfo=timezone.utc),
                                   "machine_name": (machines.get(t["machine"]) or {}).get("name")} for t in timeouts]},
        }
