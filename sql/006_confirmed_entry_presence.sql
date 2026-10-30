CREATE OR ALTER VIEW backoffice.EntryPresence AS
SELECT e.*,
 CONVERT(bit,CASE WHEN e.IsOpen=1 AND EXISTS(
  SELECT 1 FROM scheduler.LobbyTable t
  JOIN scheduler.MachineAssignment observer ON observer.SiteId=t.SiteId AND observer.MachineId=t.ObserverMachineId
  JOIN scheduler.TableSeat seat ON seat.SiteId=t.SiteId AND seat.TableId=t.TableId
  JOIN dbo.BotAccount bot ON bot.BotAccountId=e.BotAccountId
  WHERE t.SiteId=e.SiteId AND t.TableId=e.TableId
   AND t.FullSnapshotUtc>=DATEADD(second,-60,SYSUTCDATETIME())
   AND t.ObserverEpoch=observer.WorkerEpoch AND observer.IsReady=1
   AND observer.LastHeartbeatUtc>=DATEADD(second,-180,SYSUTCDATETIME())
   AND seat.ObservedUtc>=DATEADD(second,-60,SYSUTCDATETIME())
   AND (seat.BotAccountId=e.BotAccountId OR seat.Username=bot.Username)
 ) THEN 1 ELSE 0 END) AS IsConfirmedSeat
FROM scheduler.Entry e;
GO
GRANT SELECT ON backoffice.EntryPresence TO poker_backoffice_app;
