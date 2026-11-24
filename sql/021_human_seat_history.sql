-- Anonymous minute samples. MachineId=0 means the site; other scopes count each
-- ring table with an open seated bot entry on that PC once, including shared tables.
-- Unknown/stale/incomplete snapshots stay NULL. Tournament registration totals
-- cannot identify humans and are deliberately excluded.
IF OBJECT_ID('backoffice.HumanSeatSample') IS NULL
CREATE TABLE backoffice.HumanSeatSample(
 SiteId int NOT NULL,MachineId int NOT NULL,SampledUtc datetime2(0) NOT NULL,
 Humans int NULL,ObservedHumans int NOT NULL,FreshTables int NOT NULL,TotalTables int NOT NULL,
 CONSTRAINT PK_HumanSeatSample PRIMARY KEY(SiteId,MachineId,SampledUtc));
GO
CREATE OR ALTER PROCEDURE backoffice.SampleHumanSeats AS
BEGIN
 SET NOCOUNT ON;
 SET XACT_ABORT ON;
 DECLARE @now datetime2(3)=SYSUTCDATETIME(),@minute datetime2(0),@lock int;
 SET @minute=DATEADD(minute,DATEDIFF(minute,0,@now),0);
 BEGIN TRANSACTION;
 EXEC @lock=sys.sp_getapplock @Resource='backoffice:human-seat-samples',
   @LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=0;
 IF @lock<0 BEGIN ROLLBACK; RETURN; END;
 SELECT s.SiteId,s.TableId,COUNT(*) AS Seats,
   SUM(CASE WHEN s.BotAccountId IS NULL AND bot.IsBot=0 THEN 1 ELSE 0 END) AS Humans,
   MIN(s.ObservedUtc) AS OldestSeat,
   SUM(CASE WHEN s.BotAccountId IS NULL AND NULLIF(LTRIM(RTRIM(s.Username)),'') IS NULL THEN 1 ELSE 0 END) AS Unidentified
 INTO #seats FROM scheduler.TableSeat s
 OUTER APPLY(SELECT COUNT(*) AS IsBot FROM dbo.BotAccount b
   JOIN scheduler.AccountPolicy p ON p.BotAccountId=b.BotAccountId
   WHERE p.SiteId=s.SiteId AND b.Username=s.Username) bot
 GROUP BY s.SiteId,s.TableId;
 SELECT l.SiteId,l.TableId,COALESCE(s.Humans,0) AS Humans,
   CASE WHEN l.FullSnapshotUtc>=DATEADD(second,-180,@now)
     AND a.IsReady=1 AND a.WorkerEpoch=l.ObserverEpoch
     AND a.LastHeartbeatUtc>=DATEADD(second,-180,@now)
     AND COALESCE(s.Seats,0)=l.OccupiedSeats AND COALESCE(s.Unidentified,0)=0
     AND (l.OccupiedSeats=0 OR s.OldestSeat>=DATEADD(second,-180,@now)) THEN 1 ELSE 0 END AS Fresh
 INTO #tables FROM scheduler.LobbyTable l
 LEFT JOIN #seats s ON s.SiteId=l.SiteId AND s.TableId=l.TableId
 LEFT JOIN scheduler.MachineAssignment a ON a.SiteId=l.SiteId AND a.MachineId=l.ObserverMachineId
 WHERE l.IsOpen=1 AND COALESCE(l.TableType,'') NOT IN ('SNG','MTT');
 SELECT SiteId,0 AS MachineId,TableId INTO #scoped FROM #tables
 UNION
 SELECT t.SiteId,e.MachineId,t.TableId FROM #tables t
 JOIN scheduler.Entry e ON e.SiteId=t.SiteId AND e.TableId=t.TableId
 WHERE e.IsOpen=1 AND e.Status='seated';
 ;WITH scopes AS (
   SELECT SiteId,0 AS MachineId,1 AS Ready FROM scheduler.Site
   UNION ALL
   SELECT SiteId,MachineId,CASE WHEN IsReady=1 AND LastHeartbeatUtc>=DATEADD(second,-180,@now) THEN 1 ELSE 0 END
   FROM scheduler.MachineAssignment
 ), totals AS (
   SELECT c.SiteId,c.MachineId,c.Ready,COUNT(t.TableId) AS TotalTables,
     COALESCE(SUM(t.Fresh),0) AS FreshTables,
     COALESCE(SUM(CASE WHEN t.Fresh=1 THEN t.Humans ELSE 0 END),0) AS ObservedHumans
   FROM scopes c LEFT JOIN #scoped m ON m.SiteId=c.SiteId AND m.MachineId=c.MachineId
   LEFT JOIN #tables t ON t.SiteId=m.SiteId AND t.TableId=m.TableId
   GROUP BY c.SiteId,c.MachineId,c.Ready
 )
 INSERT backoffice.HumanSeatSample(SiteId,MachineId,SampledUtc,Humans,ObservedHumans,FreshTables,TotalTables)
 SELECT t.SiteId,t.MachineId,@minute,
   CASE WHEN Ready=1 AND FreshTables=TotalTables AND (MachineId<>0 OR TotalTables>0)
     AND NOT EXISTS(SELECT 1 FROM scheduler.Entry e LEFT JOIN scheduler.LobbyTable l
       ON l.SiteId=e.SiteId AND l.TableId=e.TableId
       WHERE e.SiteId=t.SiteId AND e.IsOpen=1 AND e.Status='seated'
         AND (t.MachineId=0 OR e.MachineId=t.MachineId)
         AND COALESCE(l.TableType,'') NOT IN ('SNG','MTT') AND (l.TableId IS NULL OR l.IsOpen=0))
     THEN ObservedHumans ELSE NULL END,ObservedHumans,FreshTables,TotalTables
 FROM totals t WHERE NOT EXISTS(SELECT 1 FROM backoffice.HumanSeatSample h
   WHERE h.SiteId=t.SiteId AND h.MachineId=t.MachineId AND h.SampledUtc=@minute);
 COMMIT;
END;
GO
GRANT SELECT ON OBJECT::backoffice.HumanSeatSample TO poker_backoffice_app;
GRANT EXECUTE ON OBJECT::backoffice.SampleHumanSeats TO poker_scheduler_app;
