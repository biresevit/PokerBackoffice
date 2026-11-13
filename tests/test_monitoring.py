"""Monitoring page: decision speed per street / PC and missed actions."""
from datetime import datetime, timedelta, timezone

import pytest

from backoffice.monitoring import Monitoring, percentile
from backoffice.store import Context, Store
from backoffice.validation import Error

HOUR = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0, tzinfo=None)


def metric(machine, street, decisions, total, mx, bands, hour=HOUR):
    return {"machine": machine, "hour": hour, "street": street, "decisions": decisions, "total_ms": total, "max_ms": mx,
            **dict(zip(("Under250", "Under500", "Under1000", "Under2000", "Under5000", "Over5000"), bands))}


class Db:
    def __init__(self):
        self.queries = []

    def rows(self, sql, *args):
        self.queries.append((sql, args))
        if "MachineAssignment" in sql:
            return [{"id": 5, "name": "VMI3689543"}, {"id": 1030, "name": "WIN-PAJT"}]
        if "DecisionMetric" in sql:
            return [metric(5, 1, 10, 3000, 900, [4, 4, 2, 0, 0, 0]), metric(1030, 1, 10, 9000, 4000, [0, 2, 4, 2, 2, 0]),
                    metric(5, 4, 5, 6000, 2500, [0, 0, 1, 3, 1, 0], HOUR - timedelta(hours=1))]
        if "ActionTimeout" in sql:
            return [{"machine": 1030, "kind": "sit_out", "at": HOUR, "username": "dean", "table_id": "T1", "table_name": "Friday Main"},
                    {"machine": 5, "kind": "clock_acted", "at": HOUR, "username": "elio44", "table_id": "x", "table_name": None}]
        return []


def monitoring(db):
    s = Store(db, Context(3, "aad", "simo", "viewer"))
    s.site = lambda site_id, lock=False, version=None: {"id": site_id, "timezone": "Europe/Rome"}
    return Monitoring(s)


def test_summary_by_street_pc_hour_and_missed_actions():
    d = monitoring(Db()).get(1006, {})
    assert d["overall"]["decisions"] == 25 and d["overall"]["avg_ms"] == 720 and d["overall"]["max_ms"] == 4000
    pre = d["streets"][0]
    assert pre["name"] == "Preflop" and pre["decisions"] == 20 and pre["avg_ms"] == 600 and pre["p50_under_ms"] == 500
    assert {p["name"]: (p["decisions"], p["sit_out"], p["clock_acted"]) for p in d["per_machine"]} == {
        "VMI3689543": (15, 0, 1), "WIN-PAJT": (10, 1, 0)}
    assert d["missed"] == {**d["missed"], "total": 2, "sit_out": 1, "clock_acted": 1}
    assert [p["decisions"] for p in d["series"]] == [5, 20] and d["series"][1]["missed"] == 2
    streets = {s["name"]: [p["decisions"] for p in s["points"]] for s in d["series_by_street"]}
    assert streets == {"Preflop": [20], "Flop": [], "Turn": [], "River": [5]}


def test_filters_and_validation():
    db = Db()
    monitoring(db).get(1006, {"machine": "5", "opponents": "5"})
    sql, args = next(q for q in db.queries if "DecisionMetric" in q[0])
    assert "MachineId=%s" in sql and "Opponents>=%s" in sql and args[-2:] == (5, 5)
    with pytest.raises(Error):
        monitoring(Db()).get(1006, {"machine": "999"})
    with pytest.raises(Error):
        monitoring(Db()).get(1006, {"from": "2026-11-13T10:00:00Z", "to": "2026-11-13T09:00:00Z"})
    assert percentile([0, 0, 0, 0, 0, 3], .5) is None and percentile([], .5) is None
