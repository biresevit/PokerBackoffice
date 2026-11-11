from copy import deepcopy
from types import SimpleNamespace

import pytest

from backoffice.casino_settings import CasinoSettings
from backoffice.store import Store,Context
from backoffice.validation import Error


COLUMNS=('use_help','help_min_big_blind','help_vs_humans','profile_vs_humans','profile_max_stake','profile_min_big_blind','profile_in_tournaments')


class DB:
    def __init__(self):self.setting=None;self.writes=[];self.other_customer=False;self.players=[]
    def rows(self,sql,*args):
        assert 'FROM dbo.CasinoSettingsPlayer' in sql and args==('Evenbet',14004)
        return [{'feature':f,'name':n} for f,n in sorted(self.players)]
    def one(self,sql,*args):
        if 'FROM scheduler.Site' in sql:
            if 'CustomerId<>' in sql:return {'SiteId':2} if self.other_customer else None
            return {'id':1,'name':'Evenbet','customer_id':14004} if args==(1,14004) else None
        if 'FROM dbo.CasinoSettings' in sql:
            assert args==('Evenbet',14004)
            return deepcopy(self.setting)
        raise AssertionError(sql)
    def execute(self,sql,*args):
        self.writes.append((sql,args))
        if 'DELETE dbo.CasinoSettingsPlayer' in sql:
            assert args[:2]==('Evenbet',14004);self.players=[p for p in self.players if p[0]!=args[2]]
        elif 'INSERT dbo.CasinoSettingsPlayer' in sql:
            assert args[:2]==(14004,'Evenbet');self.players.append(args[2:])
        elif 'dbo.CasinoSettings' in sql:
            assert args[-2:]==('Evenbet',14004)
            self.setting=dict(zip(COLUMNS,args[:-2]),updated='now')


def service(role='operator',customer=14004):
    db=DB();store=Store(db,Context(customer,'test','owner',role))
    return CasinoSettings(store),db


def body(s):
    return {**{k:v for k,v in s.get(1)['settings'].items() if k!='updated'},'version':s.get(1)['version']}


def test_missing_settings_are_read_only_until_explicit_save():
    s,db=service();d=s.get(1)
    assert not d['exists'] and d['editable'] and not db.writes
    assert d['settings']==dict(use_help=False,help_min_big_blind=None,help_vs_humans='Everyone',profile_vs_humans='Everyone',
        profile_max_stake=None,profile_min_big_blind=None,profile_in_tournaments=True,help_players=[],profile_players=[])


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


def test_another_customer_on_the_same_casino_does_not_block_scoped_settings():
    s,db=service();db.other_customer=True
    assert s.get(1)['editable'] and s.get(1)['customer_id']==14004
    s.save(1,body(s))
    assert db.setting['profile_vs_humans']=='Everyone'


@pytest.mark.parametrize('change',[
    {'use_help':'false'},{'profile_in_tournaments':1},{'profile_vs_humans':'weak'},
    {'profile_max_stake':'Unlimited'},{'Casino':'BluffPoker'},{'customer_id':1},
    {'help_vs_humans':'Winners'},{'help_min_big_blind':-1},{'help_min_big_blind':True},{'profile_min_big_blind':'abc'},
    {'help_players':'player1'},{'help_players':['x'*101]},{'profile_players':['bad'+chr(10)+'name']},{'help_players':[f'p{i}' for i in range(501)]},
])
def test_validation_and_casino_overrides_are_rejected(change):
    s,db=service()
    with pytest.raises(Error) as error:s.save(1,{**body(s),**change})
    assert error.value.status==400 and not db.writes


def test_card_sharing_and_profile_conditions_with_player_lists():
    s,db=service()
    d=s.save(1,{**body(s),'use_help':True,'help_min_big_blind':'4','help_vs_humans':'ListedPlayers',
        'help_players':[' player1','Player2','player2','',"player3"],'profile_vs_humans':'ListedPlayers',
        'profile_min_big_blind':2,'profile_players':['winner']})
    v=d['settings']
    assert v['help_min_big_blind']==4 and v['help_vs_humans']=='ListedPlayers' and v['profile_min_big_blind']==2
    assert v['help_players']==['Player2','player1','player3'] and v['profile_players']==['winner']
    assert sorted(db.players)==[('CardSharing','Player2'),('CardSharing','player1'),('CardSharing','player3'),('Profile','winner')]
    audit=[a for q,a in db.writes if 'AuditLog' in q][-1]
    assert 'player1' in audit[-1]


def test_unchanged_lists_are_not_rewritten_and_zero_minimum_means_none():
    s,db=service();s.save(1,{**body(s),'help_players':['a'],'profile_players':['b']})
    before=len([q for q,_ in db.writes if 'CasinoSettingsPlayer' in q])
    d=s.save(1,{**body(s),'help_min_big_blind':0,'profile_min_big_blind':''})
    assert len([q for q,_ in db.writes if 'CasinoSettingsPlayer' in q])==before
    assert d['settings']['help_min_big_blind'] is None and d['settings']['profile_min_big_blind'] is None


def test_a_player_list_change_makes_an_open_page_stale():
    s,db=service();s.save(1,body(s));v=body(s)
    db.players.append(('Profile','someone'))
    with pytest.raises(Error,match='changed'):s.save(1,v)


@pytest.mark.parametrize('change',[
    {'use_help':True,'help_vs_humans':'ListedPlayers','help_players':[]},
    {'profile_vs_humans':'ListedPlayers','profile_players':['  ']},
])
def test_listed_players_mode_needs_a_player(change):
    s,db=service()
    with pytest.raises(Error,match='at least one player') as error:s.save(1,{**body(s),**change})
    assert error.value.status==400 and not db.writes


def test_empty_card_sharing_list_is_fine_while_card_sharing_is_off():
    s,db=service()
    assert s.save(1,{**body(s),'use_help':False,'help_vs_humans':'ListedPlayers'})['settings']['help_vs_humans']=='ListedPlayers'
