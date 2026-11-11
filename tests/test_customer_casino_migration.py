"""Migration/provisioning verification; every database change is rolled back."""
import os,sys,uuid
from pathlib import Path

import pytest

from backoffice.db import connect,Database

pytestmark=pytest.mark.skipif(os.getenv('BACKOFFICE_TEST_SQL')!='1',reason='Opt-in SQL tests')


def test_customer_defaults_site_enable_isolation_and_legacy_reader():
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
    from admin import migrate
    conn=connect()
    defaults={'UseHelp':False,'ProfileVsHumans':'Everyone','ProfileMaxStake':None,'ProfileInTournaments':True}
    try:
        db=Database(conn);migrate(db)
        ids=[];machines=[]
        for _ in range(2):
            name='__casino_settings_rollback_'+uuid.uuid4().hex
            cid=db.one('INSERT dbo.Customer(CustomerName) OUTPUT inserted.CustomerId AS id VALUES(%s)',name)['id'];ids.append(cid)
            h=uuid.uuid4().hex[:10].upper();mac='AA-'+ '-'.join(h[i:i+2] for i in range(0,10,2))
            mid=db.one("INSERT dbo.CustomerMachine(CustomerId,MacAddress,Casino,Platform) VALUES(%s,%s,'Evenbet','EvenBet'); SELECT CONVERT(int,SCOPE_IDENTITY()) AS id",cid,mac)['id'];machines.append(mid)
            assert db.one("SELECT UseHelp,ProfileVsHumans,ProfileMaxStake,ProfileInTournaments FROM dbo.CasinoSettings WHERE CustomerId=%s AND Casino='Evenbet'",cid)==defaults
        a,b=ids
        db.execute("EXEC dbo.CasinoSettings_Upsert @Casino='Evenbet',@CustomerId=%s,@UseHelp=1,@SolverVsHumans=1,@SolverMinBigBlind=4,@SolverMinBuyIn=20",a)
        db.execute('UPDATE dbo.CustomerMachine SET IsActive=0 WHERE MachineId=%s; UPDATE dbo.CustomerMachine SET IsActive=1 WHERE MachineId=%s',machines[0],machines[0])
        for casino in ('Evenbet','BluffPoker'):
            db.execute("INSERT scheduler.Site(CustomerId,Casino,Platform,TimeZone,CurrencyCode) VALUES(%s,%s,'EvenBet','Europe/Budapest','DEMO')",a,casino)
        db.execute("UPDATE scheduler.Site SET SchedulingEnabled=1 WHERE CustomerId=%s",a)
        assert db.one("SELECT UseHelp,ProfileVsHumans,ProfileMaxStake,ProfileInTournaments FROM dbo.CasinoSettings WHERE CustomerId=%s AND Casino='BluffPoker'",a)==defaults
        aa=db.rows("EXEC dbo.CasinoSettings_List @CustomerId=%s,@Casino='Evenbet'",a)
        bb=db.rows("EXEC dbo.CasinoSettings_List @CustomerId=%s,@Casino='Evenbet'",b)
        assert len(aa)==len(bb)==1 and aa[0]['UseHelp'] and aa[0]['ProfileVsHumans']=='Never' and not aa[0]['ProfileInTournaments']
        assert aa[0]['SolverVsHumans'] and aa[0]['SolverMinBigBlind']==4 and aa[0]['SolverMinBuyIn']==20 and aa[0]['HelpMinBuyIn'] is None
        assert not bb[0]['SolverVsHumans'] and bb[0]['SolverMinBigBlind'] is None
        assert {k:bb[0][k] for k in defaults}==defaults
        legacy=db.rows('EXEC dbo.CasinoSettings_List')
        assert all({k:r[k] for k in defaults}==defaults for r in legacy)
        with pytest.raises(Exception,match='CustomerId is required'):
            db.execute("EXEC dbo.CasinoSettings_Upsert @Casino='Evenbet',@UseHelp=1")
    finally:conn.rollback();conn.close()
