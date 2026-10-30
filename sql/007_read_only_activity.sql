-- Clock-based reporting stays correct even between background cleanup ticks.
CREATE OR ALTER VIEW backoffice.EntryPresence AS
SELECT e.*,
 CONVERT(bit,CASE WHEN owner.IsReady=1 AND owner.WorkerEpoch=e.WorkerEpoch
   AND owner.LastHeartbeatUtc>=DATEADD(second,-180,SYSUTCDATETIME()) THEN 1 ELSE 0 END) AS IsLiveOwner,
 CONVERT(bit,CASE WHEN e.IsOpen=1 AND owner.IsReady=1 AND owner.WorkerEpoch=e.WorkerEpoch
   AND owner.LastHeartbeatUtc>=DATEADD(second,-180,SYSUTCDATETIME()) AND EXISTS(
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
FROM scheduler.Entry e
LEFT JOIN scheduler.MachineAssignment owner ON owner.SiteId=e.SiteId AND owner.MachineId=e.MachineId;
GO
CREATE OR ALTER VIEW backoffice.SessionActivity AS
SELECT s.SessionId,s.SiteId,s.BotAccountId,s.MachineId,s.WorkerEpoch,s.StartedUtc,s.PlannedEndUtc,
 CASE WHEN s.IsOpen=1 AND (a.LastHeartbeatUtc IS NULL OR a.LastHeartbeatUtc<DATEADD(second,-180,SYSUTCDATETIME()))
   THEN CASE WHEN s.StartedUtc>DATEADD(second,180,COALESCE(a.LastHeartbeatUtc,'19000101'))
     THEN s.StartedUtc ELSE DATEADD(second,180,a.LastHeartbeatUtc) END
   ELSE s.ActualEndUtc END AS ActualEndUtc,
 CONVERT(bit,CASE WHEN s.IsOpen=1 AND (a.LastHeartbeatUtc IS NULL OR a.LastHeartbeatUtc<DATEADD(second,-180,SYSUTCDATETIME())) THEN 0 ELSE s.IsOpen END) AS IsOpen,
 CASE WHEN s.IsOpen=1 AND (a.LastHeartbeatUtc IS NULL OR a.LastHeartbeatUtc<DATEADD(second,-180,SYSUTCDATETIME()))
   THEN N'machine_offline' ELSE s.EndReason END AS EndReason
FROM scheduler.AccountSession s
JOIN scheduler.MachineAssignment a ON a.SiteId=s.SiteId AND a.MachineId=s.MachineId;
GO
GRANT SELECT ON backoffice.SessionActivity TO poker_backoffice_app;
