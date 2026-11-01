-- backoffice.EntryPresence selects e.* from scheduler.Entry. SQL Server binds that column list when
-- the view is created, so 023 adding Entry.PlayTableId shifted the view's computed columns:
-- IsLiveOwner read PlayTableId (NULL) and the Overview counted no bot entries.
-- Any migration that adds a column to scheduler.Entry must refresh this view again.
EXEC sp_refreshview N'backoffice.EntryPresence';
