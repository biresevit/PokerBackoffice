"""MTT plans on the Schedule page (MTT tab, 2026-11-12)."""
from datetime import datetime, timedelta, timezone

import pytest

from backoffice.mtts import Mtts, planned_target
from backoffice.store import Context, Store
from backoffice.validation import Error

NOW = datetime.now(timezone.utc).replace(microsecond=0)


def lobby(name, start, state="registering", info=None, observed=NOW, table="T1", players=3):
    return {"TableId": table, "TableName": name, "GameType": "NLH", "MinBuyIn": 0, "StartUtc": start.replace(tzinfo=None),
            "TournamentState": state, "IsOpen": True, "OccupiedSeats": players, "MaxSeats": 3000,
            "ObservedUtc": observed.replace(tzinfo=None), "TournamentInfo": info}


class Db:
    def __init__(self, tables=(), plans=(), bots=()):
        self.tables, self.plans, self.bots, self.executed = list(tables), list(plans), list(bots), []

    def rows(self, sql, *args):
        if "FROM scheduler.MttPlan" in sql:
            return self.plans
        if "GROUP BY e.TableId" in sql:
            return self.bots
        if "LobbyTable" in sql:
            return self.tables
        return []

    def one(self, sql, *args):
        return None

    def execute(self, sql, *args):
        self.executed.append((" ".join(sql.split()), args))


def mtts(db, role="operator"):
    s = Store(db, Context(3, "aad", "simo", role))
    s.site = lambda site_id, lock=False, version=None: {"id": site_id, "timezone": "Europe/Rome", "currency": "EUR"}
    s.audits = []
    s.audit = lambda *a: s.audits.append(a)
    return Mtts(s)


def plan(series, total=10, rebuy=2, addon=1, early=40, hours=2):
    return {"SeriesName": series, "TotalBots": total, "RebuyBots": rebuy, "AddonBots": addon, "EarlyPercent": early,
            "EarlyHours": hours, "UpdatedUtc": NOW}


def test_list_groups_daily_instances_under_one_plan_and_skips_rows_the_lobby_no_longer_lists():
    late = '{"late_reg": true, "rebuy": false, "reentry": true, "addon": false}'
    db = Db([lobby("Night Owl Freeroll 12/11", NOW + timedelta(hours=1), info=late, table="T1"),
             lobby("Night Owl Freeroll 13/11", NOW + timedelta(hours=25), info=late, table="T2"),
             lobby("Night Owl Freeroll 11/11", NOW - timedelta(hours=23), state="completed", table="T0"),
             lobby("Gone MTT", NOW + timedelta(hours=2), observed=NOW - timedelta(hours=5), table="T9")],
            [plan("Night Owl Freeroll")], [{"TableId": "T1", "registered": 3, "open_entries": 3, "rebuy": 1, "addon": 0}])
    d = mtts(db).list(1006)
    assert [s["series"] for s in d["series"]] == ["Night Owl Freeroll"]
    s = d["series"][0]
    assert s["recurrence"] == {"recurring": True, "count": 3, "pattern": "daily"}
    assert [i["id"] for i in s["instances"]] == ["T1", "T2"] and s["instances"][0]["bots"] == 3
    assert s["info"]["reentry"] is True and s["plan"]["total"] == 10
    assert s["instances"][0]["plan"]["early"] == 4 and s["instances"][0]["plan"]["late"] == 6
    assert d["unlisted_plans"] == []


def test_save_validates_and_upserts_the_plan_without_touching_the_site_version():
    db = Db()
    result = mtts(db).save(1006, {"series": "Night Owl Freeroll", "total": 20, "rebuy": 5, "addon": 0,
                                  "early_percent": 40, "early_hours": 2})
    assert result["plan"] == {"total": 20, "rebuy": 5, "addon": 0, "early_percent": 40, "early_hours": 2.0}
    sql, args = db.executed[0]
    assert sql.startswith("MERGE scheduler.MttPlan") and args[:2] == (1006, "Night Owl Freeroll")
    assert not any("ConfigVersion" in s for s, _ in db.executed)
    with pytest.raises(Error):
        mtts(db).save(1006, {"series": "X", "total": 3, "rebuy": 4})
    with pytest.raises(Error):
        mtts(db).save(1006, {"series": "X", "total": 3, "early_percent": 120})
    with pytest.raises(Error) as viewer:
        mtts(db, role="viewer").save(1006, {"series": "X", "total": 3})
    assert viewer.value.status == 403


def test_planned_target_counts_registrations_due_across_planned_starts():
    start = NOW + timedelta(hours=1)
    db = Db([lobby("Night Owl Freeroll 12/11", start)], [plan("Night Owl Freeroll", total=10, hours=2)])
    target = planned_target(db, 1006, NOW, NOW)
    assert target(start - timedelta(hours=3)) == 0
    assert 0 < target(NOW) < 10 and target(start - timedelta(minutes=2)) == 10
