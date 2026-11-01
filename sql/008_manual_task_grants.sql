-- Manual Join/Leave tasks (Tasks page) write the scheduler's own rows: an Entry and, when the bot
-- has none yet, an AccountLease for a join, then a Command and its Outbox row for either kind.
GRANT INSERT ON scheduler.Entry TO poker_backoffice_app;
GRANT INSERT ON scheduler.Command TO poker_backoffice_app;
GRANT INSERT ON scheduler.Outbox TO poker_backoffice_app;
GRANT INSERT ON scheduler.AccountLease TO poker_backoffice_app;
