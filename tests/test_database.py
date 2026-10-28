"""Opt-in Azure SQL integration tests: every change is rolled back."""
import os
import sys
from pathlib import Path
import pytest
from backoffice.db import connect, Database
from backoffice.store import Context, Store
from backoffice.validation import Error
from backoffice.histories import Histories

pytestmark=pytest.mark.skipif(os.getenv("BACKOFFICE_TEST_SQL")!="1",reason="Opt-in SQL tests")


@pytest.fixture
def store():
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
    from admin import migrate
    conn=connect()
    try:
        db=Database(conn)
        migrate(db)
        yield Store(db,Context(14004,"test","rollback","operator"))
    finally:
        conn.rollback()
        conn.close()


def test_all_read_pages_and_foreign_scope(store):
    for name in ("overview","accounts","schedule","stakes","tables","machines"):
        assert isinstance(getattr(store,name)(1),dict)
    assert isinstance(store.tasks(1,{}),dict)
    assert isinstance(store.sessions(1,{}),dict)
    metrics=store.entry_metrics(1,{"from":"2026-10-28","to":"2026-10-28"})
    assert metrics["timezone"]=="Europe/Budapest" and metrics["points"]
    machine=store.machines(1)["items"][0]
    resources=store.machine_metrics(1,machine["id"],{"hours":"24"})
    assert resources["hours"]==24 and isinstance(resources["points"],list)
    with pytest.raises(Error) as e:
        Store(store.db,Context(1,"test","other","operator")).accounts(1)
    assert e.value.status==404
    assert isinstance(Histories(store).list(1,{"from":"2026-10-01","to":"2026-10-31"})["items"],list)


def test_import_upsert_preserves_preferences_and_stale_version(store):
    before=store.accounts(1)
    original=next(r for r in before["items"] if r["username"]=="monica")
    body={"csv":"username,profile\nmonica,Maniac\n__backoffice_rollback_test,Strong Tight", "version":before["version"]}
    preview=store.import_accounts(1,body)
    body["token"]=preview["token"]
    store.import_accounts(1,body,apply=True)
    rows=store.accounts(1)["items"]
    monica=next(r for r in rows if r["username"]=="monica")
    assert monica["strategy"]==1
    assert monica["buy_in_weights"]==original["buy_in_weights"]
    assert monica["stake"]==original["stake"]
    assert not next(r for r in rows if r["username"]=="__backoffice_rollback_test")["enabled"]
    with pytest.raises(Error) as e:
        store.import_accounts(1,body,apply=True)
    assert e.value.status==409


def test_viewer_and_foreign_hand_blocked(store):
    viewer=Store(store.db,Context(14004,"test","viewer","viewer"))
    with pytest.raises(Error) as e:
        viewer.save_schedule(1,{"version":viewer.site(1)["version"],"windows":[]})
    assert e.value.status==403
    with pytest.raises(Error) as e:
        Histories(store).download(1,[1])
    assert e.value.status==404


def test_schedule_and_machine_save(store):
    schedule=store.schedule(1)
    schedule["windows"]=[{"weekday":1,"start_minute":1020,"end_minute":1080,"target":56}]
    store.save_schedule(1,schedule)
    assert store.schedule(1)["windows"][0]["target"]==56
    m=store.machines(1)["items"][0]
    store.save_machine(1,m["id"],{**m,"max_entries":57})
    assert store.machines(1)["items"][0]["max_entries"]==57


def test_account_session_settings_and_synthetic_guard(store):
    accounts=store.accounts(1)
    row=next(a for a in accounts["items"] if a["username"]=="monica")
    row.update(version=accounts["version"],session_min_minutes=80,session_max_minutes=150,session_cooldown_minutes=8)
    store.update_account(1,row["id"],row)
    saved=next(a for a in store.accounts(1)["items"] if a["id"]==row["id"])
    assert (saved["session_min_minutes"],saved["session_max_minutes"],saved["session_cooldown_minutes"])==(80,150,8)
    data=store.accounts(1)
    synthetic=next(a for a in data["items"] if a["synthetic"])
    with pytest.raises(Error) as e:
        store.update_account(1,synthetic["id"],{**synthetic,"version":data["version"],"enabled":True})
    assert e.value.status==400
