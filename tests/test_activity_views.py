"""Exercise deployed reporting expressions with synthetic CTEs; no live rows change."""
import os
from datetime import timedelta
import pytest
from backoffice.db import session

pytestmark=pytest.mark.skipif(os.getenv('BACKOFFICE_TEST_SQL')!='1',reason='Opt-in SQL tests')


def definition(db,name):
    source=db.one('SELECT OBJECT_DEFINITION(OBJECT_ID(%s)) AS source',name)['source']
    assert source,'Reporting migration must be applied'
    return source[source.index('SELECT '):]


@pytest.mark.parametrize('age,scheduled,open_expected',[(150,False,True),(181,False,False),(None,False,False),(181,True,False)])
def test_session_deadline_is_reported_without_running_cleanup(age,scheduled,open_expected):
    with session() as db:
        now=db.one('SELECT SYSUTCDATETIME() AS now')['now']
        started=now+timedelta(minutes=10) if scheduled else now-timedelta(hours=1)
        heartbeat=now-timedelta(seconds=age) if age is not None else None
        body=definition(db,'backoffice.SessionActivity').replace('scheduler.AccountSession','fake_sessions').replace('scheduler.MachineAssignment','fake_machines')
        row=db.one("""WITH fake_sessions AS(SELECT 1 AS SessionId,1 AS SiteId,1 AS BotAccountId,1 AS MachineId,
            'epoch' AS WorkerEpoch,CAST(%s AS datetime2) AS StartedUtc,CAST(%s AS datetime2) AS PlannedEndUtc,
            CAST(NULL AS datetime2) AS ActualEndUtc,CAST(1 AS bit) AS IsOpen,CAST(NULL AS nvarchar(80)) AS EndReason),
            fake_machines AS(SELECT 1 AS SiteId,1 AS MachineId,CAST(%s AS datetime2) AS LastHeartbeatUtc)
            """+body,started,started+timedelta(hours=1),heartbeat)
        assert row['IsOpen']==open_expected
        if not open_expected:
            assert row['EndReason']=='machine_offline'
            expected_end=max(started,heartbeat+timedelta(seconds=180)) if heartbeat else started
            assert row['ActualEndUtc']==expected_end


@pytest.mark.parametrize('age,owner_ready,expected',[(150,1,True),(181,1,False),(150,0,False)])
def test_fresh_observer_cannot_keep_an_offline_owners_entry_running(age,owner_ready,expected):
    with session() as db:
        now=db.one('SELECT SYSUTCDATETIME() AS now')['now']
        body=definition(db,'backoffice.EntryPresence')
        for table,fake in [('scheduler.Entry','fake_entries'),('scheduler.MachineAssignment','fake_machines'),('scheduler.LobbyTable','fake_tables'),('scheduler.TableSeat','fake_seats'),('dbo.BotAccount','fake_bots')]:
            body=body.replace(table,fake)
        row=db.one("""WITH fake_entries AS(SELECT 1 AS SiteId,1 AS MachineId,4 AS BotAccountId,'42' AS TableId,
            'owner' AS WorkerEpoch,CAST(1 AS bit) AS IsOpen),
            fake_machines AS(SELECT 1 AS SiteId,1 AS MachineId,'owner' AS WorkerEpoch,%s AS IsReady,CAST(%s AS datetime2) AS LastHeartbeatUtc
                UNION ALL SELECT 1,2,'observer',1,CAST(%s AS datetime2)),
            fake_tables AS(SELECT 1 AS SiteId,'42' AS TableId,2 AS ObserverMachineId,'observer' AS ObserverEpoch,CAST(%s AS datetime2) AS FullSnapshotUtc),
            fake_seats AS(SELECT 1 AS SiteId,'42' AS TableId,4 AS BotAccountId,'hero' AS Username,CAST(%s AS datetime2) AS ObservedUtc),
            fake_bots AS(SELECT 4 AS BotAccountId,'hero' AS Username)
            """+body,owner_ready,now-timedelta(seconds=age),now,now,now)
        assert row['IsLiveOwner']==expected and row['IsConfirmedSeat']==expected
