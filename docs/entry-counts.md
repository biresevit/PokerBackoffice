# Confirmed seat counts and reconciliation

Overview, Accounts, active Sessions and Machines use backoffice.EntryPresence. A running entry requires an open managed entry plus a bot identity present in a table snapshot from the last 60 seconds, published by the current observer epoch with a fresh heartbeat. Live tables applies the same snapshot freshness checks and resolves known account usernames when needed. Pending, joining and unconfirmed journal records are separate from confirmed seated counts; they still retain capacity/ownership until safely reconciled. Ended sessions show historical attempts, not concurrent running entries.

The worker reconciles open entries against complete fresh table snapshots newer than their last confirmation. It leaves in-flight join/leave operations untouched. Confirmed absence closes the entry, ends an otherwise empty session and releases its account lease. Failed reconnect candidates have independent observation clocks so they cannot make cached seats on an older connection appear fresh. Reconnect preserves surviving tables even when another seat has disappeared. Resume commands are best-effort: a server rejection is logged and cannot terminate all restart reconciliation. Recovery never buys into an already observed seat a second time.

Overview/Accounts/Sessions entry counts refresh every 15 seconds. Historical chart endpoints use the live confirmed count for the current point and cap open stale intervals; older activity/accounting cannot be reconstructed exactly from overwritten snapshots and is not guessed or silently rewritten.

The local worker repair procedure verifies the signed release and ZIP hash, confirms every PDecision package file is identical, gracefully stops only the worker and uses startup seat reconciliation. It retains the running PDecision process and records the repaired release in the updater state and maintenance audit. Release 2026.10.29.6 includes the full repair; candidate 2026.10.29.5 was disabled after its live resume-command rejection exposed an unhandled startup error.

## Overview loading and offline reporting

Dashboard reads do not call `scheduler.ExpireOfflineMachines`. The scheduler timer owns cleanup writes. `backoffice.EntryPresence` requires a ready, fresh owner with a matching worker epoch as well as a fresh observer snapshot. `backoffice.SessionActivity` reports a session ended at the heartbeat deadline even before the timer persists cleanup; it never updates live rows. Thus reading a page cannot hold cleanup write locks against controllers.

Overview reads account totals and machine health directly instead of loading full account settings and machine details. Its six data queries are bounded independently of the number of machines. The activity chart loads independently after the cards render and has its own retry button; a chart outage preserves the summary.
