"""Connection-local temporary tables exercise the real SQL without changing live settings."""
import os

import pytest

from backoffice.casino_settings import CasinoSettings
from backoffice.db import Database,connect
from backoffice.store import Context,Store
from backoffice.validation import Error


pytestmark=pytest.mark.skipif(os.getenv('BACKOFFICE_TEST_SQL')!='1',reason='Opt-in SQL tests')


def test_casino_settings_sql_preserves_other_casinos_and_rejects_stale_saves():
    conn=connect()
    class TemporaryDB(Database):
        def query(self,sql):return sql.replace('dbo.CasinoSettings','#CasinoSettings').replace('scheduler.Site','#Site')
        def rows(self,sql,*args):return super().rows(self.query(sql),*args)
        def execute(self,sql,*args):return super().execute(self.query(sql),*args)
    try:
        db=TemporaryDB(conn)
        db.execute('''CREATE TABLE #CasinoSettings(CustomerId int NOT NULL,Casino nvarchar(50),UseHelp bit NOT NULL,
            ProfileVsHumans varchar(20) NOT NULL,ProfileMaxStake varchar(10) NULL,ProfileInTournaments bit NOT NULL,
            UpdatedUtc datetime2(0) NOT NULL DEFAULT SYSUTCDATETIME(),PRIMARY KEY(CustomerId,Casino));
            INSERT #CasinoSettings(CustomerId,Casino,UseHelp,ProfileVsHumans,ProfileMaxStake,ProfileInTournaments)
                VALUES(14004,'BluffPoker',0,'Everyone',NULL,1),(99124,'Evenbet',1,'Never','High',0);
            CREATE TABLE #Site(SiteId int,CustomerId int,Casino nvarchar(50),TimeZone nvarchar(50),
                CurrencyCode varchar(5),ConfigVersion bigint,SchedulingEnabled bit);
            INSERT #Site VALUES(99123,14004,'Evenbet','Europe/Budapest','DEMO',1,1);''')
        store=Store(db,Context(14004,'test','temp','operator'));audit=[]
        store.audit=lambda *args:audit.append(args)
        s=CasinoSettings(store);before=s.get(99123)
        assert not before['exists']
        body={**before['settings'],'version':before['version'],'profile_vs_humans':'WeakHumans','profile_max_stake':'Low'}
        saved=s.save(99123,body)
        assert saved['exists'] and saved['settings']['profile_max_stake']=='Low' and audit
        with pytest.raises(Error,match='changed'):s.save(99123,body)
        edited=s.save(99123,{**body,'version':saved['version'],'use_help':True,'profile_max_stake':None})
        assert edited['settings']['use_help'] and edited['settings']['profile_max_stake'] is None
        assert db.one("SELECT ProfileVsHumans,ProfileMaxStake FROM #CasinoSettings WHERE CustomerId=99124 AND Casino='Evenbet'")=={'ProfileVsHumans':'Never','ProfileMaxStake':'High'}
        assert db.one("SELECT ProfileVsHumans,UseHelp FROM #CasinoSettings WHERE Casino='BluffPoker'")=={'ProfileVsHumans':'Everyone','UseHelp':False}
    finally:
        conn.rollback();conn.close()
