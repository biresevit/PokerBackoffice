from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from backoffice.live_cards import enrich, merge_cards


def table():
    return dict(table_id='123',hand_id='456',board=['2c','3d','4s'],game='NLH',hero='kate',
                seats=[dict(seat=0,name='kate',hero=True,in_game=True,cards=['ac','ad']),
                       dict(seat=1,name='richard',hero=False,in_game=True,cards=[]),
                       dict(seat=2,name='human',hero=False,in_game=True,cards=[])])


def snapshot():
    p=table();p['hero']='richard'
    for s in p['seats']:s['hero']=s['seat']==1;s['cards']=['kh','kd'] if s['hero'] else []
    return p


def test_shares_only_source_hero_and_never_overwrites_visible_cards():
    p=table();s=snapshot();s['seats'][2]['cards']=['qs','qh']
    assert merge_cards(p,[dict(payload=json.dumps(s),username='richard')])==1
    assert p['seats'][1]['cards']==['kh','kd'] and p['seats'][1]['shared_cards']
    assert p['seats'][2]['cards']==[] and p['seats'][0]['cards']==['ac','ad']
    assert merge_cards(p,[dict(payload=json.dumps(s),username='richard')])==0


@pytest.mark.parametrize('key,value',[('hand_id','457'),('table_id','124'),('board',[]),
                                     ('hero','human'),('game','PLO4')])
def test_wrong_hand_table_board_identity_or_game_stays_hidden(key,value):
    p=table();s=snapshot();s[key]=value
    assert merge_cards(p,[dict(payload=json.dumps(s),username='richard')])==0


@pytest.mark.parametrize('change',['name','seat','unknown','partial','duplicate'])
def test_wrong_seat_or_invalid_private_cards_stay_hidden(change):
    p=table();s=snapshot();h=s['seats'][1]
    if change=='name':h['name']='someone else'
    if change=='seat':h['seat']=4
    if change=='unknown':h['cards']=['','']
    if change=='partial':h['cards']=['kh']
    if change=='duplicate':h['cards']=['kh','kh']
    assert merge_cards(p,[dict(payload=json.dumps(s),username='richard')])==0


@pytest.mark.parametrize('game,count',[('NLH',2),('PLO4',4),('PLO5',5)])
def test_all_supported_games(game,count):
    p=table();s=snapshot();p['game']=s['game']=game
    s['seats'][1]['cards']=['kh','kd','qs','qh','jc'][:count]
    assert merge_cards(p,[dict(payload=json.dumps(s),username='richard')])==1


class DB:
    def __init__(self,enabled):self.enabled=enabled;self.queries=[]
    def one(self,q,*args):
        assert 'WHERE Casino=%s AND CustomerId=%s' in q
        assert args==('Evenbet',14004)
        return {'use_help':self.enabled}
    def rows(self,q,*args):
        self.queries.append(q)
        assert 'c.CustomerId=%s' in q
        assert 14004 in args and 'viewer' in args
        if 'DECLARE @expires' in q:return []
        assert "DATEADD(second,-10" in q and "r.Status='active'" in q
        return [dict(payload=json.dumps(snapshot()),username='richard')]


@pytest.mark.parametrize('enabled,age,status,shared',[(False,0,'active',0),(True,0,'active',1),
                                                   (True,11,'active',0),(True,0,'expired',0)])
def test_setting_scope_freshness_and_live_lease(enabled,age,status,shared):
    db=DB(enabled);store=SimpleNamespace(db=db,site=lambda _:dict(name='Evenbet'),
        ctx=SimpleNamespace(customer_id=14004,subject='viewer'))
    row=dict(payload=deepcopy(table()),table_id='123',status=status,
             captured=datetime.now(timezone.utc)-timedelta(seconds=age))
    enrich(store,1,row)
    assert row['payload']['card_sharing']==dict(enabled=enabled,shared_bots=shared)
    assert bool(row['payload']['seats'][1]['cards'])==bool(shared)
    if not enabled or status!='active':assert not db.queries
