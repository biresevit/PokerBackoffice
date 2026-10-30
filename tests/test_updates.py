"""Rollout tests run inside rollback transactions and never stop applications."""
import os,uuid
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
from pathlib import Path
import sys
import pytest
from backoffice.db import connect,Database
from backoffice.store import Store,Context
from backoffice.updates import Updates,agent_request
from backoffice.validation import Error

pytestmark=pytest.mark.skipif(os.getenv('BACKOFFICE_TEST_SQL')!='1',reason='Opt-in SQL tests')


@pytest.fixture
def env():
    conn=connect()
    try:
        db=Database(conn)
        release=str(uuid.uuid4())
        db.execute("INSERT scheduler.UpdateRelease(ReleaseId,Label,PDecisionVersion,PokerControllerVersion,ManifestJson,Signature,PublicKey,ArtifactUrl) VALUES(%s,%s,'1.0.0.29','0.1.0-test','{}','test','test','https://example.blob.core.windows.net/test.zip')",release,'rollback-'+release)
        db.execute('UPDATE scheduler.MachineAssignment SET IsReady=1,LastHeartbeatUtc=SYSUTCDATETIME() WHERE SiteId=1 AND MachineId=1')
        store=Store(db,Context(14004,'test','updates-test','operator'))
        updates=Updates(store)
        cfg=updates.enroll(1,{'machine_id':1})
        headers={'x-updater-token':cfg['Token']}
        body={'instance_id':str(uuid.uuid4()),'agent_version':'test','apps_running':True}
        agent_request(db,1,headers,body,'poll')
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'ScheduleController'))
        class Adapter:
            def one(self,sql,*args):return db.one(sql.replace('?','%s'),*args)
            def rows(self,sql,*args):return db.rows(sql.replace('?','%s'),*args)
            def execute(self,sql,*args):return db.execute(sql.replace('?','%s'),*args)
        yield db,updates,release,headers,body,Adapter()
    finally:conn.rollback();conn.close()


def test_serial_preflight_drain_install_and_recovery(env):
    from schedule_controller.update_rollouts import tick_rollouts
    db,updates,release,headers,body,adapter=env
    first=updates.create(1,{'release_id':release,'machines':[1]})['id']
    second=updates.create(1,{'release_id':release,'machines':[1]})['id']
    stamp=datetime.now(timezone.utc)
    tick_rollouts(adapter,stamp)
    task=db.one('SELECT * FROM scheduler.MachineUpdateTask WHERE RolloutId=%s',first)
    assert task['Status']=='preparing'
    assert db.one('SELECT MaintenanceTaskId FROM scheduler.MachineAssignment WHERE SiteId=1 AND MachineId=1')['MaintenanceTaskId'] is None
    poll=agent_request(db,1,headers,body,'poll')['task']
    assert poll['id']==str(task['TaskId'])
    agent_request(db,1,headers,{**body,'task_id':poll['id'],'phase':'staged'},'report')
    tick_rollouts(adapter,stamp)
    assert db.one('SELECT Status FROM scheduler.MachineUpdateTask WHERE RolloutId=%s',first)['Status']=='draining'
    assert db.one('SELECT Status FROM scheduler.MachineUpdateTask WHERE RolloutId=%s',second)['Status']=='queued'
    with pytest.raises(Error):agent_request(db,1,headers,{**body,'task_id':poll['id'],'phase':'installing'},'report')
    original=db.rows('SELECT EntryId FROM scheduler.Entry WHERE SiteId=1 AND MachineId=1 AND IsOpen=1')
    db.execute("UPDATE scheduler.Entry SET IsOpen=0,Status='closed',ClosedUtc=SYSUTCDATETIME() WHERE SiteId=1 AND MachineId=1 AND IsOpen=1")
    tick_rollouts(adapter,stamp)
    assert db.one('SELECT Status FROM scheduler.MachineUpdateTask WHERE RolloutId=%s',first)['Status']=='stopping'
    agent_request(db,1,headers,{**body,'task_id':poll['id'],'phase':'installing'},'report')
    agent_request(db,1,headers,{**body,'task_id':poll['id'],'phase':'verifying'},'report')
    with pytest.raises(Error):agent_request(db,1,headers,{**body,'task_id':poll['id'],'phase':'resuming','pdecision_version':'wrong'},'report')
    agent_request(db,1,headers,{**body,'task_id':poll['id'],'phase':'resuming','pdecision_version':'1.0.0.29','controller_version':'0.1.0-test'},'report')
    assert db.one('SELECT MaintenanceTaskId FROM scheduler.MachineAssignment WHERE SiteId=1 AND MachineId=1')['MaintenanceTaskId'] is None
    tick_rollouts(adapter,stamp+timedelta(seconds=10))
    assert db.one('SELECT Status FROM scheduler.MachineUpdateTask WHERE RolloutId=%s',second)['Status']=='queued'
    # Restore original live rows within the transaction to prove recovery is
    # required before completion, without generating poker-site actions.
    for row in original:db.execute("UPDATE scheduler.Entry SET IsOpen=1,Status='seated',ClosedUtc=NULL WHERE EntryId=%s",row['EntryId'])
    future=stamp+timedelta(seconds=65)
    db.execute('UPDATE scheduler.MachineUpdateAgent SET LastHeartbeatUtc=%s WHERE MachineId=1',future.replace(tzinfo=None))
    tick_rollouts(adapter,future)
    assert db.one('SELECT Status FROM scheduler.MachineUpdateTask WHERE RolloutId=%s',first)['Status']=='completed'


def test_rollout_scope_tokens_and_failure_pause(env):
    from schedule_controller.update_rollouts import tick_rollouts
    db,updates,release,headers,body,adapter=env
    with pytest.raises(Error) as error:agent_request(db,1,{'x-updater-token':'invalid'},body,'poll')
    assert error.value.status==401
    with pytest.raises(Error):agent_request(db,2,headers,body,'poll')
    with pytest.raises(Error):Updates(Store(db,Context(1,'test','foreign','operator'))).list(1)
    with pytest.raises(Error):Updates(Store(db,Context(14004,'test','viewer','viewer'))).create(1,{'release_id':release,'machines':[1]})
    with pytest.raises(Error):updates.create(1,{'release_id':release,'machines':[999999]})
    rid=updates.create(1,{'release_id':release,'machines':[1]})['id']
    tick_rollouts(adapter,datetime.now(timezone.utc))
    task=agent_request(db,1,headers,body,'poll')['task']
    agent_request(db,1,headers,{**body,'task_id':task['id'],'phase':'failed','detail':'Signature test failure'},'report')
    assert db.one('SELECT Status FROM scheduler.UpdateRollout WHERE RolloutId=%s',rid)['Status']=='paused'
    assert db.one('SELECT MaintenanceTaskId FROM scheduler.MachineAssignment WHERE SiteId=1 AND MachineId=1')['MaintenanceTaskId'] is None
    updates.control(1,rid,{'action':'cancel'})
    assert db.one('SELECT Status FROM scheduler.UpdateRollout WHERE RolloutId=%s',rid)['Status']=='cancelled'
