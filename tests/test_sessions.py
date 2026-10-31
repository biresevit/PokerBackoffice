from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from backoffice.sessions import Sessions
from backoffice.validation import Error

SESSION='12345678-1234-1234-1234-123456789abc'


class Database:
    def __init__(self,accounts=None,machines=None,entries=False,open_session=False,is_open=True):
        self.accounts=accounts if accounts is not None else [
            dict(id=4,username='emma',min_minutes=60,max_minutes=90,in_session=False,cooling_down=False)]
        self.machines=machines if machines is not None else [
            dict(id=1,name='MSI',epoch='epoch-1',capacity=15,entries=3,available=True),
            dict(id=2,name='PC-19',epoch='epoch-2',capacity=15,entries=1,available=True),
            dict(id=3,name='PC-17',epoch='epoch-3',capacity=15,entries=0,available=False)]
        self.entries,self.open_session,self.is_open=entries,open_session,is_open
        self.writes=[]
    def rows(self,sql,*args):
        if 'AccountPolicy p' in sql:return self.accounts
        if 'MachineAssignment a' in sql:return self.machines
        raise AssertionError(sql)
    def one(self,sql,*args):
        if 'AccountLease WITH(UPDLOCK' in sql:return None
        if 'WHERE BotAccountId=%s AND IsOpen=1' in sql:return {'SessionId':'x'} if self.open_session else None
        if 'SELECT BotAccountId FROM scheduler.AccountSession' in sql:return {'BotAccountId':4}
        if 'SELECT IsOpen,StartedUtc' in sql:return {'IsOpen':self.is_open,'StartedUtc':datetime(2026,1,1)}
        if 'FROM scheduler.Entry WHERE SessionId' in sql:return {'EntryId':'e'} if self.entries else None
        raise AssertionError(sql)
    def execute(self,sql,*args):self.writes.append((sql,args))


def service(db,role='operator'):
    site={'timezone':'Europe/Budapest'}
    store=SimpleNamespace(db=db,ctx=SimpleNamespace(role=role,subject='owner',customer_id=1),site=lambda s:site,audit=lambda *a:None)
    return Sessions(store)


def local(delta):
    return (datetime.now(ZoneInfo('Europe/Budapest'))+delta).strftime('%Y-%m-%dT%H:%M')


def test_create_with_any_bot_and_machine_picks_most_free_ready_machine():
    db=Database()
    result=service(db).create(1,{'account_id':'any','machine_id':'any','start':local(timedelta()),'end':local(timedelta(hours=1))})
    assert result['bot']=='emma' and result['machine']=='PC-19'
    sql,args=db.writes[0]
    assert 'IsManual' in sql and args[2:5]==(4,2,'epoch-2')


def test_create_converts_site_local_times_to_utc():
    db=Database()
    start=local(timedelta(hours=2))
    service(db).create(1,{'account_id':'4','machine_id':'1','start':start,'end':local(timedelta(hours=3))})
    stored=db.writes[0][1][5]
    expected=datetime.strptime(start,'%Y-%m-%dT%H:%M').replace(tzinfo=ZoneInfo('Europe/Budapest')).astimezone(timezone.utc).replace(tzinfo=None)
    assert stored==expected


@pytest.mark.parametrize('body,message',[
    ({'machine_id':'3','end':None},'not online'),
    ({'end':'past'},'at least one minute'),
    ({'end':'day'},'at most 24 hours'),
])
def test_create_rejects_invalid_requests(body,message):
    ends={None:local(timedelta(hours=1)),'past':local(timedelta()),'day':local(timedelta(hours=30))}
    request={'account_id':'4','machine_id':body.get('machine_id','1'),'start':local(timedelta()),'end':ends[body['end']]}
    with pytest.raises(Error,match=message):service(Database()).create(1,request)


def test_create_refuses_a_bot_that_already_has_an_open_session():
    with pytest.raises(Error,match='already has an open session'):
        service(Database(open_session=True)).create(1,{'account_id':'4','end':local(timedelta(hours=1))})


def test_any_bot_skips_bots_in_session_or_cooling_down():
    accounts=[dict(id=4,username='emma',min_minutes=60,max_minutes=90,in_session=True,cooling_down=False),
              dict(id=5,username='kate',min_minutes=60,max_minutes=90,in_session=False,cooling_down=True)]
    with pytest.raises(Error,match='No bot is available'):
        service(Database(accounts=accounts)).create(1,{'end':local(timedelta(hours=1))})


def test_view_only_users_cannot_create_or_stop():
    with pytest.raises(Error,match='view-only'):service(Database(),'viewer').create(1,{'end':local(timedelta(hours=1))})
    with pytest.raises(Error,match='view-only'):service(Database(),'viewer').stop(1,SESSION)


def test_stop_without_tables_closes_the_session_directly():
    db=Database(entries=False)
    assert service(db).stop(1,SESSION)=={'status':'stopped'}
    assert "IsOpen=0,EndReason='stopped_by_operator'" in db.writes[0][0]


def test_stop_with_tables_ends_the_plan_and_lets_the_worker_close_it():
    db=Database(entries=True)
    assert service(db).stop(1,SESSION)=={'status':'leaving_tables'}
    sql=db.writes[0][0]
    assert 'THEN SYSUTCDATETIME()' in sql and "EndReason='stopped_by_operator'" in sql and 'IsOpen' not in sql


def test_stop_rejects_an_ended_session():
    with pytest.raises(Error,match='already ended'):service(Database(is_open=False)).stop(1,SESSION)
