"""Validate tournament counts with connection-local SQL fixtures; never change live data."""
import os
from types import SimpleNamespace

import pytest
from backoffice.db import connect,Database
from backoffice.mtts import Mtts

pytestmark=pytest.mark.skipif(os.getenv('BACKOFFICE_TEST_SQL')!='1',reason='Opt-in isolated SQL fixtures')


def test_overview_counts_unique_bots_and_keeps_original_registration_after_return_failure():
    conn=connect();base=Database(conn)
    class Fixtures:
        def rows(self,sql,*args):
            for table in ('scheduler.LobbyTable','backoffice.EntryPresence','scheduler.Command','scheduler.MttPlan'):
                sql=sql.replace(table,'#'+table.split('.')[1])
            return base.rows(sql,*args)
    try:
        for sql in [
            'CREATE TABLE #LobbyTable(SiteId int,TableId varchar(10),TableName nvarchar(100),GameType varchar(10),StartUtc datetime2,TournamentState varchar(20),TableType varchar(10))',
            'CREATE TABLE #EntryPresence(EntryId int,SiteId int,TableId varchar(10),BotAccountId int,Status varchar(20),LastConfirmedUtc datetime2,SeatedUtc datetime2,IsOpen bit,IsLiveOwner bit)',
            'CREATE TABLE #Command(EntryId int,Kind varchar(10),Status varchar(20),ResultCode varchar(80),PayloadJson nvarchar(max))',
            'CREATE TABLE #MttPlan(SiteId int,SeriesName nvarchar(100),TotalBots int)',
            "INSERT #LobbyTable VALUES(1006,'T1','Turbo Night','NLH','2026-11-16T22:59:00','completed','MTT'),(1006,'T2','Tomorrow','NLH','2026-11-16T23:00:00','registering','MTT')",
            "INSERT #MttPlan VALUES(1006,'Turbo Night',10)",
            """INSERT #EntryPresence VALUES
                (1,1006,'T1',1,'seated',SYSUTCDATETIME(),SYSUTCDATETIME(),1,1),
                (2,1006,'T1',1,'closed',SYSUTCDATETIME(),SYSUTCDATETIME(),0,0),
                (3,1006,'T1',2,'closed',NULL,NULL,0,0),
                (4,1006,'T1',3,'failed',NULL,NULL,0,0),
                (5,1006,'T1',4,'closed',SYSUTCDATETIME(),SYSUTCDATETIME(),0,0),
                (6,1006,'T1',5,'seated',SYSUTCDATETIME(),SYSUTCDATETIME(),1,0),
                (7,1006,'T1',6,'closed',NULL,NULL,0,0)""",
            """INSERT #Command VALUES
                (3,'join','succeeded',NULL,'{}'),
                (3,'join','failed','return_failed','{"resume_registration":true}'),
                (4,'join','failed','registration_failed','{}'),
                (7,'join','succeeded','registration_gone','{"resume_registration":true}')""",
        ]:base.execute(sql)
        store=SimpleNamespace(db=Fixtures(),ctx=None,site=lambda sid:dict(timezone='Europe/Rome'))
        result=Mtts(store).overview(1006,{'from':'2026-11-16','to':'2026-11-16'})
        assert len(result['items'])==1
        assert result['totals']==dict(scheduled=10,registered=4,running=1,ever_seated=3)
    finally:
        conn.rollback();conn.close()
