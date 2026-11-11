import pytest

from backoffice import db


class Cursor:
    def __init__(self,conn):self.conn=conn
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def execute(self,sql,params=None):
        if self.conn.broken:raise OSError('link down')
        self.conn.statements.append(sql)
    def fetchall(self):return [(1,)]
    def nextset(self):return False


class Conn:
    def __init__(self):self.statements=[];self.commits=0;self.rollbacks=0;self.closed=False;self.broken=False
    def cursor(self):return Cursor(self)
    def commit(self):self.commits+=1
    def rollback(self):self.rollbacks+=1
    def close(self):self.closed=True


@pytest.fixture
def pool(monkeypatch):
    conns=[];clock=[1000.0]
    monkeypatch.setattr(db,'connect',lambda:conns.append(Conn()) or conns[-1])
    monkeypatch.setattr(db,'_pool',[])
    monkeypatch.setattr(db.time,'monotonic',lambda:clock[0])
    return conns,clock


def test_sequential_requests_share_one_login(pool):
    conns,_=pool
    for _ in range(5):
        with db.session() as d:d.execute('SELECT 1')
    assert len(conns)==1 and conns[0].commits==5 and not conns[0].closed


def test_failed_request_rolls_back_and_drops_the_connection(pool):
    conns,_=pool
    with pytest.raises(ValueError):
        with db.session():raise ValueError('bad request')
    assert conns[0].rollbacks==1 and conns[0].closed and db._pool==[]
    with db.session():pass
    assert len(conns)==2


def test_idle_connection_is_pinged_and_replaced_when_dead(pool):
    conns,clock=pool
    with db.session():pass
    clock[0]+=db.IDLE_PING_SECONDS+1
    conns[0].broken=True
    with db.session():pass
    assert len(conns)==2 and conns[0].closed


def test_long_idle_or_old_connections_are_not_reused(pool):
    conns,clock=pool
    with db.session():pass
    clock[0]+=db.IDLE_LIMIT_SECONDS+1
    with db.session():pass
    assert len(conns)==2 and conns[0].closed


def test_concurrent_requests_use_separate_connections_and_pool_is_bounded(pool):
    conns,_=pool
    stack=[db.session() for _ in range(db.POOL_SIZE+2)]
    for s in stack:s.__enter__()
    for s in stack:s.__exit__(None,None,None)
    assert len(conns)==db.POOL_SIZE+2
    assert len(db._pool)==db.POOL_SIZE and sum(c.closed for c in conns)==2
