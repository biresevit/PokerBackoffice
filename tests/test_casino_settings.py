from copy import deepcopy
from types import SimpleNamespace

import pytest

from backoffice.casino_settings import CasinoSettings
from backoffice.store import Store,Context
from backoffice.validation import Error


class DB:
    def __init__(self):self.setting=None;self.writes=[];self.other_customer=False
    def one(self,sql,*args):
        if 'FROM scheduler.Site' in sql:
            if 'CustomerId<>' in sql:return {'SiteId':2} if self.other_customer else None
            return {'id':1,'name':'Evenbet','customer_id':14004} if args==(1,14004) else None
        if 'FROM dbo.CasinoSettings' in sql:
            assert args==('Evenbet',)
            return deepcopy(self.setting)
        raise AssertionError(sql)
    def execute(self,sql,*args):
        self.writes.append((sql,args))
        if 'dbo.CasinoSettings' in sql:
            assert args[-1]=='Evenbet'
            self.setting=dict(zip(('use_help','profile_vs_humans','profile_max_stake','profile_in_tournaments'),args[:-1]),updated='now')


def service(role='operator',customer=14004):
    db=DB();store=Store(db,Context(customer,'test','owner',role))
    return CasinoSettings(store),db


def body(s):
    return {**{k:v for k,v in s.get(1)['settings'].items() if k!='updated'},'version':s.get(1)['version']}


def test_missing_settings_are_read_only_until_explicit_save():
    s,db=service();d=s.get(1)
    assert not d['exists'] and d['editable'] and not db.writes
    assert d['settings']==dict(use_help=False,profile_vs_humans='Everyone',profile_max_stake=None,profile_in_tournaments=True)


def test_create_and_edit_only_the_authorized_casino_and_audit():
    s,db=service();v=body(s)
    d=s.save(1,{**v,'profile_vs_humans':'WeakHumans','profile_max_stake':'Low','profile_in_tournaments':False})
    assert d['exists'] and d['settings']['profile_max_stake']=='Low'
    assert any('INSERT backoffice.AuditLog' in q for q,_ in db.writes)
    s.save(1,{**body(s),'profile_max_stake':None,'profile_vs_humans':'Never'})
    assert db.setting['profile_max_stake'] is None


def test_stale_save_never_overwrites_newer_values():
    s,db=service();v=body(s);s.save(1,v);before=len(db.writes)
    with pytest.raises(Error,match='changed'):s.save(1,{**v,'use_help':True})
    assert len(db.writes)==before and not db.setting['use_help']


@pytest.mark.parametrize('role,customer,status',[('viewer',14004,403),('operator',1,404)])
def test_customer_scope_and_viewer_permissions(role,customer,status):
    s,db=service(role,customer)
    with pytest.raises(Error) as error:s.save(1,{})
    assert error.value.status==status and not db.writes


def test_shared_casino_cannot_be_changed_by_one_customer():
    s,db=service();db.other_customer=True
    assert not s.get(1)['editable']
    with pytest.raises(Error,match='shared'):s.save(1,body(s))
    assert not db.writes


@pytest.mark.parametrize('change',[
    {'use_help':'false'},{'profile_in_tournaments':1},{'profile_vs_humans':'weak'},
    {'profile_max_stake':'Unlimited'},{'Casino':'BluffPoker'},{'customer_id':1},
])
def test_validation_and_casino_overrides_are_rejected(change):
    s,db=service()
    with pytest.raises(Error) as error:s.save(1,{**body(s),**change})
    assert error.value.status==400 and not db.writes
