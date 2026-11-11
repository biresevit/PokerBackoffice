"""Exercise tournament eligibility against SQL using connection-local tables only."""
import os
from types import SimpleNamespace

import pytest

from backoffice.db import Database, connect
from backoffice.manual_tasks import ManualTasks

pytestmark = pytest.mark.skipif(os.getenv('BACKOFFICE_TEST_SQL') != '1', reason='Opt-in SQL tests')


def test_manual_registration_includes_open_late_mtts_and_rechecks_closure():
    conn = connect()

    class TemporaryDB(Database):
        def rows(self, sql, *args):
            sql = sql.replace('scheduler.LobbyTable', '#Lobby').replace('scheduler.StakeBand', '#Bands')
            return super().rows(sql, *args)

    try:
        db = TemporaryDB(conn)
        db.execute("""CREATE TABLE #Bands (SiteId int,Tier varchar(10),TournamentMinBuyIn decimal(18,4),
            TournamentMaxBuyIn decimal(18,4));
            INSERT #Bands VALUES (1,'high',10,50);
            CREATE TABLE #Lobby (SiteId int,TableId varchar(50),TableName nvarchar(200),TableType varchar(5),
                MinBuyIn decimal(18,4),OccupiedSeats int,MaxSeats int,StartUtc datetime2,
                TournamentState varchar(12),IsOpen bit,GameType varchar(5),ObservedUtc datetime2);
            INSERT #Lobby VALUES
            (1,'late','Late MTT','MTT',20,100,1000,DATEADD(minute,-30,SYSUTCDATETIME()),'running',1,'NLH',SYSUTCDATETIME()),
            (1,'closed','Closed MTT','MTT',20,100,1000,DATEADD(minute,-30,SYSUTCDATETIME()),'running',0,'NLH',SYSUTCDATETIME()),
            (1,'soon','Starts soon','MTT',20,100,1000,DATEADD(second,30,SYSUTCDATETIME()),'registering',1,'NLH',SYSUTCDATETIME()),
            (1,'stale','Stale late MTT','MTT',20,100,1000,DATEADD(minute,-30,SYSUTCDATETIME()),'running',1,'NLH',DATEADD(minute,-6,SYSUTCDATETIME())),
            (1,'done','Completed','MTT',20,100,1000,SYSUTCDATETIME(),'completed',1,'NLH',SYSUTCDATETIME()),
            (1,'sng','Open SNG','SNG',20,5,6,NULL,'registering',1,'NLH',SYSUTCDATETIME()),
            (1,'full','Full SNG','SNG',20,6,6,NULL,'registering',1,'NLH',SYSUTCDATETIME()),
            (1,'running-sng','Running SNG','SNG',20,5,6,NULL,'running',1,'NLH',SYSUTCDATETIME()),
            (2,'other','Other site','MTT',20,100,1000,SYSUTCDATETIME(),'running',1,'NLH',SYSUTCDATETIME());""")
        manual = ManualTasks(SimpleNamespace(db=db, excluded_tournaments=lambda site: []))
        rows = {t['id']: t for t in manual.tournaments(1)}
        assert set(rows) == {'late', 'soon', 'sng'}
        assert rows['late']['late_registration'] is True
        assert rows['soon']['late_registration'] is False
        assert rows['late']['tiers'] == ['high']
        db.execute("UPDATE #Lobby SET IsOpen=0 WHERE TableId='late'")
        assert 'late' not in {t['id'] for t in manual.tournaments(1)}
    finally:
        conn.rollback()
        conn.close()
