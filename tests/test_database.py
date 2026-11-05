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
    assert metrics["timezone"]=="Europe/Budapest" and metrics["points"] and metrics["format"]=="RING"
    for fmt in ("SNG","MTT"):
        assert store.entry_metrics(1,{"from":"2026-10-28","to":"2026-10-28","format":fmt})["format"]==fmt
    overview=store.overview(1)
    assert set(overview["targets"])=={"RING","SNG","MTT"} and all(e["format"] in overview["targets"] for e in overview["entries"])
    machine=store.machines(1)["items"][0]
    resources=store.machine_metrics(1,machine["id"],{"hours":"24"})
    assert resources["hours"]==24 and isinstance(resources["points"],list)
    with pytest.raises(Error) as e:
        Store(store.db,Context(1,"test","other","operator")).accounts(1)
    assert e.value.status==404
    assert isinstance(Histories(store).list(1,{"from":"2026-10-01","to":"2026-10-31"})["items"],list)


def test_overview_and_chart_are_read_only_with_bounded_query_counts(store):
    class ReadOnly:
        def __init__(self,db):self.db=db;self.count=0
        def one(self,*args):self.count+=1;return self.db.one(*args)
        def rows(self,*args):self.count+=1;return self.db.rows(*args)
        def execute(self,*args):raise AssertionError('A dashboard read attempted a write')
    for name,limit in [('overview',6),('entry_metrics',4)]:
        db=ReadOnly(store.db);reader=Store(db,store.ctx)
        getattr(reader,name)(1,{}) if name=='entry_metrics' else reader.overview(1)
        assert db.count<=limit


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


def test_import_stores_the_login_and_never_returns_the_password(store):
    version=store.accounts(1)["version"]
    body={"csv":"username,password,email\n__backoffice_login_test,s3cret,login_test@bots.example.invalid\n","version":version}
    preview=store.import_accounts(1,body)
    assert preview["changes"][0]["email"]=="login_test@bots.example.invalid" and "password" not in preview["changes"][0]
    store.import_accounts(1,dict(body,token=preview["token"]),apply=True)
    row=store.db.one("""SELECT b.LoginEmail,b.LoginPassword,p.MaxSngEntries FROM dbo.BotAccount b
        JOIN scheduler.AccountPolicy p ON p.BotAccountId=b.BotAccountId WHERE b.Username='__backoffice_login_test'""")
    assert (row["LoginEmail"],row["LoginPassword"])==("login_test@bots.example.invalid","s3cret")
    # a new password for the same account is an update; a blank one leaves it as it is
    version=store.accounts(1)["version"]
    body={"csv":"username,password,email\n__backoffice_login_test,n3w,login_test@bots.example.invalid\n","version":version}
    assert store.import_accounts(1,body)["counts"]["update"]==1
    body={"csv":"username,password,email\n__backoffice_login_test,,\n","version":version}
    assert store.import_accounts(1,body)["counts"]["unchanged"]==1


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
    store.db.execute("UPDATE TOP(1) scheduler.AccountPolicy SET DeletedUtc=NULL WHERE SiteId=1 AND IsSynthetic=1")
    data=store.accounts(1)
    synthetic=next(a for a in data["items"] if a["synthetic"])
    with pytest.raises(Error) as e:
        store.update_account(1,synthetic["id"],{**synthetic,"version":data["version"],"enabled":True})
    assert e.value.status==400


def test_machine_timeout_closes_sessions_at_deadline_and_fences_worker(store):
    db=store.db
    # Match the live worker lock order to avoid a Machine/Entry deadlock.
    db.one("SELECT WorkerEpoch FROM scheduler.MachineAssignment WITH(UPDLOCK,HOLDLOCK) WHERE SiteId=1 AND MachineId=1")
    history=db.one("SELECT TOP(1) EntryId,SessionId FROM scheduler.Entry WHERE SiteId=1 AND MachineId=1 AND SessionId IS NOT NULL ORDER BY CreatedUtc DESC")
    if not history:
        pytest.skip("Needs a historical machine entry")
    # All changes are rolled back by the fixture, including epoch and heartbeat.
    db.execute("UPDATE scheduler.Entry SET IsOpen=0,Status='closed',ClosedUtc=SYSUTCDATETIME() WHERE SiteId=1 AND MachineId=1 AND IsOpen=1")
    db.execute("UPDATE scheduler.AccountSession SET IsOpen=0,ActualEndUtc=CASE WHEN StartedUtc>SYSUTCDATETIME() THEN StartedUtc ELSE SYSUTCDATETIME() END WHERE SiteId=1 AND MachineId=1 AND IsOpen=1")
    db.execute("UPDATE scheduler.Entry SET IsOpen=1,Status='seated',CreatedUtc=DATEADD(hour,-1,SYSUTCDATETIME()),SeatedUtc=DATEADD(hour,-1,SYSUTCDATETIME()),ClosedUtc=NULL WHERE EntryId=%s",history["EntryId"])
    db.execute("UPDATE scheduler.AccountSession SET IsOpen=1,StartedUtc=DATEADD(hour,-1,SYSUTCDATETIME()),PlannedEndUtc=DATEADD(hour,1,SYSUTCDATETIME()),ActualEndUtc=NULL WHERE SessionId=%s",history["SessionId"])
    db.execute("UPDATE scheduler.MachineAssignment SET IsReady=1,LastHeartbeatUtc=DATEADD(second,-150,SYSUTCDATETIME()) WHERE SiteId=1 AND MachineId=1")
    pending=db.one("SELECT TOP(1) EntryId FROM scheduler.Entry WHERE SiteId=1 AND MachineId=1 AND EntryId<>%s AND (BotAccountId<>(SELECT BotAccountId FROM scheduler.Entry WHERE EntryId=%s) OR TableId<>(SELECT TableId FROM scheduler.Entry WHERE EntryId=%s))",history["EntryId"],history["EntryId"],history["EntryId"])
    assert pending
    db.execute("UPDATE scheduler.Entry SET IsOpen=1,Status='reserved',SeatedUtc=NULL,ClosedUtc=NULL WHERE EntryId=%s",pending["EntryId"])
    db.execute('UPDATE scheduler.Entry SET WorkerEpoch=(SELECT WorkerEpoch FROM scheduler.MachineAssignment WHERE SiteId=1 AND MachineId=1) WHERE EntryId IN (%s,%s)',history['EntryId'],pending['EntryId'])
    db.execute("DELETE scheduler.TableSeat WHERE SiteId=1")
    machine_counts=next(m for m in store.machines(1)["items"] if m["id"]==1)
    # A seated journal record without a fresh seat snapshot is unconfirmed.
    assert machine_counts["entries"]==0
    assert machine_counts["pending_entries"]==2
    before=db.one("SELECT WorkerEpoch FROM scheduler.MachineAssignment WHERE SiteId=1 AND MachineId=1")
    db.execute("EXEC scheduler.ExpireOfflineMachines @CustomerId=14004")
    assert db.one("SELECT IsOpen FROM scheduler.Entry WHERE EntryId=%s",history["EntryId"])["IsOpen"]
    db.execute("UPDATE scheduler.MachineAssignment SET LastHeartbeatUtc=DATEADD(second,-181,SYSUTCDATETIME()) WHERE SiteId=1 AND MachineId=1")
    deadline=db.one("SELECT DATEADD(second,180,LastHeartbeatUtc) AS deadline FROM scheduler.MachineAssignment WHERE SiteId=1 AND MachineId=1")["deadline"]
    logical=db.one('SELECT IsOpen,ActualEndUtc,EndReason FROM backoffice.SessionActivity WHERE SessionId=%s',history['SessionId'])
    assert not logical['IsOpen'] and logical['ActualEndUtc']==deadline and logical['EndReason']=='machine_offline'
    assert db.one('SELECT IsOpen FROM scheduler.AccountSession WHERE SessionId=%s',history['SessionId'])['IsOpen']
    assert db.one('SELECT IsConfirmedSeat,IsLiveOwner FROM backoffice.EntryPresence WHERE EntryId=%s',history['EntryId'])=={'IsConfirmedSeat':False,'IsLiveOwner':False}
    db.execute("EXEC scheduler.ExpireOfflineMachines @CustomerId=1")
    assert db.one("SELECT IsOpen FROM scheduler.Entry WHERE EntryId=%s",history["EntryId"])["IsOpen"]
    db.execute("EXEC scheduler.ExpireOfflineMachines @CustomerId=14004")
    entry=db.one("SELECT IsOpen,ClosedUtc FROM scheduler.Entry WHERE EntryId=%s",history["EntryId"])
    session=db.one("SELECT IsOpen,ActualEndUtc,EndReason FROM scheduler.AccountSession WHERE SessionId=%s",history["SessionId"])
    machine=db.one("SELECT WorkerEpoch,IsReady FROM scheduler.MachineAssignment WHERE SiteId=1 AND MachineId=1")
    assert not entry["IsOpen"] and entry["ClosedUtc"]==deadline
    assert not session["IsOpen"] and session["ActualEndUtc"]==deadline and session["EndReason"]=="machine_offline"
    assert not machine["IsReady"] and machine["WorkerEpoch"]!=before["WorkerEpoch"]
    db.execute("EXEC scheduler.ExpireOfflineMachines @CustomerId=14004")
    assert db.one("SELECT WorkerEpoch FROM scheduler.MachineAssignment WHERE SiteId=1 AND MachineId=1")=={"WorkerEpoch":machine["WorkerEpoch"]}


@pytest.mark.parametrize("status",["all","pending","claimed","succeeded","failed","cancelled","expired","uncertain"])
def test_task_status_filter_matches_count_and_items(store,status):
    result=store.tasks(1,{"status":status,"page_size":"10"})
    expected=store.db.one("SELECT COUNT(*) AS n FROM scheduler.Command WHERE SiteId=1 AND (%s='all' OR Status=%s)",status,status)["n"]
    expected+=store.db.one("""SELECT COUNT(*) AS n FROM scheduler.MachineUpdateTask WHERE SiteId=1 AND (%s='all' OR
        CASE WHEN Status='queued' THEN 'pending' WHEN Status='completed' THEN 'succeeded'
        WHEN Status IN ('failed','rolled_back') THEN 'failed' WHEN Status='cancelled' THEN 'cancelled' ELSE 'claimed' END=%s)""",status,status)['n']
    assert result["total"]==expected
    assert all(status=="all" or row["status"]==status for row in result["items"])
    with pytest.raises(Error) as error:
        store.tasks(1,{"status":"invalid"})
    assert error.value.status==400


def test_session_result_filter(store):
    baseline=store.sessions(1,{"page_size":"100"})
    for value in ["active","scheduled","closed",*baseline["result_options"]]:
        result=store.sessions(1,{"result":value,"page_size":"100"})
        for item in result["items"]:
            if value=="active": assert item["is_open"] and not item["is_scheduled"]
            elif value=="scheduled": assert item["is_scheduled"]
            elif value=="closed": assert not item["is_open"]
            else: assert not item["is_open"] and item["end_reason"]==value
        assert result["total"]>=len(result["items"])
    with pytest.raises(Error):
        store.sessions(1,{"result":"invalid"})


def test_session_current_entries_exclude_closed_attempts(store):
    # Reproduce an account at its current entry count plus a failed attempt,
    # without persisting changes or sending any poker commands.
    row=store.db.one("SELECT TOP(1) s.SessionId,e.EntryId,b.Username FROM scheduler.AccountSession s JOIN backoffice.EntryPresence e ON e.SessionId=s.SessionId JOIN dbo.BotAccount b ON b.BotAccountId=s.BotAccountId WHERE s.SiteId=1 AND s.IsOpen=1 AND e.IsOpen=1 AND e.IsConfirmedSeat=1 ORDER BY s.StartedUtc DESC")
    if not row:pytest.skip('No open session available for rollback fixture')
    before=next(item for item in store.sessions(1,{'bot':row['Username'],'result':'active','page_size':'100'})['items'] if item['id']==row['SessionId'])
    store.db.execute("UPDATE scheduler.Entry SET IsOpen=0,Status='failed',ClosedUtc=SYSUTCDATETIME() WHERE EntryId=%s",row['EntryId'])
    after=next(item for item in store.sessions(1,{'bot':row['Username'],'result':'active','page_size':'100'})['items'] if item['id']==row['SessionId'])
    assert after['entries']==before['entries']-1
    assert after['current_entries']==after['entries']
    assert after['total_entries']==before['total_entries']
    assert after['failed_entries']==before['failed_entries']+1


def test_stale_open_entry_does_not_count_as_running_without_a_seat(store):
    row=store.db.one("SELECT TOP(1) e.EntryId,e.TableId,e.SessionId,e.BotAccountId,b.Username FROM backoffice.EntryPresence e JOIN dbo.BotAccount b ON b.BotAccountId=e.BotAccountId WHERE e.SiteId=1 AND e.IsOpen=1 AND e.IsConfirmedSeat=1")
    if not row:pytest.skip('No confirmed seat for rollback fixture')
    before=next(a for a in store.accounts(1)['items'] if a['id']==row['BotAccountId'])
    store.db.execute('DELETE scheduler.TableSeat WHERE SiteId=1 AND TableId=%s AND (BotAccountId=%s OR Username=%s)',row['TableId'],row['BotAccountId'],row['Username'])
    assert store.db.one('SELECT IsOpen FROM scheduler.Entry WHERE EntryId=%s',row['EntryId'])['IsOpen']
    after=next(a for a in store.accounts(1)['items'] if a['id']==row['BotAccountId'])
    assert after['entries']==before['entries']-1
    assert after['unconfirmed_entries']==before['unconfirmed_entries']+1
