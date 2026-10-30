import pytest
from backoffice.manual import target_minor
from backoffice.validation import Error
from backoffice.manual import Manual
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import json


@pytest.mark.parametrize('value,expected',[('1.23',123),(10,1000),('0.01',1)])
def test_manual_amount_preserves_minor_units(value,expected):
    assert target_minor(value)==expected


@pytest.mark.parametrize('value',['nan','inf','-1','0','0.001',None,True,10**20])
def test_manual_amount_rejects_nonfinite_fractional_or_invalid_values(value):
    with pytest.raises(Error):target_minor(value)


class Database:
    def __init__(self):
        now=datetime.now(timezone.utc).replace(tzinfo=None)
        self.request='12345678-1234-1234-1234-123456789abc';self.writes=[];self.owns=True
        self.row=dict(RequestId=self.request,SiteId=1,BotAccountId=4,TableId='42',MachineId=1,
            Status='active',ExpiresUtc=now+timedelta(seconds=45),CapturedUtc=now,
            PayloadJson=json.dumps({'manual':{'supported':True,'turn_key':'a'*64,'actions':['fold','call','raise'],'min_target_minor':300,'max_target_minor':1000}}))
        self.control=dict(RequestId=self.request,Enabled=True,WorkerEpoch='epoch',CurrentEpoch='epoch',ExpiresUtc=now+timedelta(seconds=45))
    def one(self,sql,*args):
        if 'sp_getapplock' in sql:return {'value':0}
        if 'LiveTableSnapshot' in sql:return self.row if self.owns else None
        if 'ManualTableControl c' in sql:return self.control
        if 'SELECT TOP(1) e.WorkerEpoch' in sql:return {'WorkerEpoch':'epoch'}
        if 'TableActionClaim' in sql:return None
        if 'SELECT ActionId,Status' in sql:return None
        raise AssertionError(sql)
    def execute(self,sql,*args):self.writes.append((sql,args))


def service(role='operator'):
    db=Database();store=SimpleNamespace(db=db,ctx=SimpleNamespace(role=role,subject='owner'),site=lambda s:None,audit=lambda *a:None)
    return Manual(store),db


def test_view_only_access_cannot_take_control():
    m,db=service('viewer')
    with pytest.raises(Error) as error:m.mode(1,db.request,{'enabled':True})
    assert error.value.status==403 and not db.writes


def test_another_users_live_request_is_not_accessible():
    m,db=service();db.owns=False
    with pytest.raises(Error) as error:m.mode(1,db.request,{'enabled':True})
    assert error.value.status==404 and not db.writes


def test_another_window_cannot_steal_a_live_manual_lease():
    m,db=service();db.control['RequestId']='other'
    with pytest.raises(Error,match='Another live window'):m.mode(1,db.request,{'enabled':True})
    assert not db.writes


@pytest.mark.parametrize('problem',['stale','turn','bounds','disabled'])
def test_manual_action_rejects_stale_or_invalid_requests(problem):
    m,db=service();body={'turn_key':'a'*64,'action':'raise','amount':'5.00'}
    if problem=='stale':db.row['CapturedUtc']-=timedelta(seconds=6)
    if problem=='turn':body['turn_key']='b'*64
    if problem=='bounds':body['amount']='100.00'
    if problem=='disabled':db.control['Enabled']=False
    with pytest.raises(Error):m.action(1,db.request,body)
    assert not db.writes


def test_valid_action_is_queued_for_exact_hero_and_turn():
    m,db=service()
    result=m.action(1,db.request,{'turn_key':'a'*64,'action':'raise','amount':'5.00'})
    assert result['status']=='queued'
    assert db.writes[0][1][-3:]==('a'*64,'raise',500)
