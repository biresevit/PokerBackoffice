"""Exercise the production sampler SQL against temporary fixtures only.

Requires the local admin SQL connection; no customer data is changed.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'api'))
from backoffice.db import connect, Database


def main():
    conn = connect()
    db = Database(conn)
    try:
        db.execute('''CREATE TABLE #Site(SiteId int);
          CREATE TABLE #MachineAssignment(SiteId int,MachineId int,IsReady bit,WorkerEpoch uniqueidentifier,LastHeartbeatUtc datetime2);
          CREATE TABLE #LobbyTable(SiteId int,TableId nvarchar(80),FullSnapshotUtc datetime2,ObserverEpoch uniqueidentifier,
            ObserverMachineId int,OccupiedSeats int,IsOpen bit,TableType varchar(4));
          CREATE TABLE #TableSeat(SiteId int,TableId nvarchar(80),BotAccountId int,Username nvarchar(100),ObservedUtc datetime2);
          CREATE TABLE #BotAccount(BotAccountId int,Username nvarchar(100));
          CREATE TABLE #AccountPolicy(SiteId int,BotAccountId int);
          CREATE TABLE #Entry(SiteId int,MachineId int,TableId nvarchar(80),IsOpen bit,Status varchar(12));
          CREATE TABLE #HumanSeatSample(SiteId int,MachineId int,SampledUtc datetime2,Humans int NULL,
            ObservedHumans int,FreshTables int,TotalTables int,PRIMARY KEY(SiteId,MachineId,SampledUtc));
          INSERT #Site VALUES(1),(2);
          DECLARE @epoch uniqueidentifier=NEWID();
          INSERT #MachineAssignment VALUES(1,5,1,@epoch,SYSUTCDATETIME()),(1,6,1,@epoch,SYSUTCDATETIME()),(2,7,1,@epoch,SYSUTCDATETIME());
          INSERT #LobbyTable VALUES(1,'ring',SYSUTCDATETIME(),@epoch,5,4,1,'RING'),
            (1,'empty',SYSUTCDATETIME(),@epoch,5,0,1,'RING'),
            (1,'tournament',SYSUTCDATETIME(),@epoch,5,99,1,'MTT'),
            (2,'other',SYSUTCDATETIME(),@epoch,7,1,1,'RING');
          INSERT #BotAccount VALUES(101,'known'),(102,'known-by-name');
          INSERT #AccountPolicy VALUES(1,101),(1,102);
          INSERT #TableSeat VALUES(1,'ring',101,'known',SYSUTCDATETIME()),
            (1,'ring',NULL,'known-by-name',SYSUTCDATETIME()),
            (1,'ring',NULL,'human-a',SYSUTCDATETIME()),(1,'ring',NULL,'human-b',SYSUTCDATETIME()),
            (2,'other',NULL,'known',SYSUTCDATETIME());
          INSERT #Entry VALUES(1,5,'ring',1,'seated'),(1,5,'ring',1,'seated'),(1,6,'ring',1,'seated');''')
        sql = (ROOT/'sql/021_human_seat_history.sql').read_text()
        body = re.split(r'CREATE OR ALTER PROCEDURE backoffice.SampleHumanSeats AS\s*', sql)[1].split('\nGO')[0]
        for schema, name in [('scheduler', n) for n in ('Site','MachineAssignment','LobbyTable','TableSeat','AccountPolicy','Entry')]+[('dbo','BotAccount'),('backoffice','HumanSeatSample')]:
            body = body.replace(schema+'.'+name, '#'+name)
        # The procedure's local temp tables need to disappear between invocations
        # in this ad-hoc fixture batch (SQL does that automatically for procedures).
        def sample():
            db.execute(body)
            db.execute('DROP TABLE #seats; DROP TABLE #tables; DROP TABLE #scoped;')
        sample()
        got = db.rows('SELECT SiteId AS site,MachineId AS pc,Humans AS humans FROM #HumanSeatSample ORDER BY SiteId,MachineId')
        assert [(r['site'],r['pc'],r['humans']) for r in got] == [(1,0,2),(1,5,2),(1,6,2),(2,0,1),(2,7,0)], got
        sample()
        assert db.one('SELECT COUNT(*) AS n FROM #HumanSeatSample')['n'] == 5
        # A stale observer must not make every human disappear from reporting.
        db.execute("DELETE #HumanSeatSample; UPDATE #MachineAssignment SET LastHeartbeatUtc=DATEADD(minute,-10,SYSUTCDATETIME()) WHERE SiteId=1")
        sample()
        assert all(r['humans'] is None for r in db.rows('SELECT Humans AS humans FROM #HumanSeatSample WHERE SiteId=1'))
        # A partial seat list and an unidentified player both remain unknown.
        db.execute("DELETE #HumanSeatSample; UPDATE #MachineAssignment SET LastHeartbeatUtc=SYSUTCDATETIME(); DELETE #TableSeat WHERE Username='human-b'")
        sample()
        assert db.one('SELECT Humans AS humans FROM #HumanSeatSample WHERE SiteId=1 AND MachineId=0')['humans'] is None
        db.execute("DELETE #HumanSeatSample; INSERT #TableSeat VALUES(1,'ring',NULL,'',SYSUTCDATETIME())")
        sample()
        assert db.one('SELECT Humans AS humans FROM #HumanSeatSample WHERE SiteId=1 AND MachineId=0')['humans'] is None
        print('PASS: bot identity fallback, site scope, shared-table deduplication, idempotence, stale and incomplete snapshots.')
    finally:
        conn.rollback()
        conn.close()


if __name__ == '__main__':
    main()
