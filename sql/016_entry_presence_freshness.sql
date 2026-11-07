-- A seat counted as confirmed only while its table's lobby snapshot and seat observation were under 60 s old.
-- BluffPoker lobby scans log in and out for every pass, so a full snapshot arrives every 60-85 s and is already
-- ~35 s old when written: about 40 percent of the time every seat of the site was unconfirmed at once and the Overview
-- showed 0 ring entries (site 1006, 2026-11-07). The reporting window now matches the 180 s heartbeat window.
-- Scheduling does not use this view; it keeps its own Site.TableFreshnessSeconds.
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
   AND t.FullSnapshotUtc>=DATEADD(second,-180,SYSUTCDATETIME())
   AND t.ObserverEpoch=observer.WorkerEpoch AND observer.IsReady=1
   AND observer.LastHeartbeatUtc>=DATEADD(second,-180,SYSUTCDATETIME())
   AND seat.ObservedUtc>=DATEADD(second,-180,SYSUTCDATETIME())
   AND (seat.BotAccountId=e.BotAccountId OR seat.Username=bot.Username)
 ) THEN 1 ELSE 0 END) AS IsConfirmedSeat
FROM scheduler.Entry e
LEFT JOIN scheduler.MachineAssignment owner ON owner.SiteId=e.SiteId AND owner.MachineId=e.MachineId;
