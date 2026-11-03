# Tournament manual control

Open a playing SNG or MTT in Live tables, select the hero and enable manual
control. Control defaults off. The existing fold/check/call/bet/raise actions,
preflop and pot shortcuts, slider, keyboard shortcuts and sit-out/return commands
use native whole tournament chips. Ring-table amounts retain currency precision.

The live request continues to identify its tournament (`T...`), while its first
snapshot pins the physical playing-table ID. Manual modes, action claims and
commands use that physical ID. Both the website and worker check that the same
hero, current machine epoch, turn and playing table are still valid before an
action is sent. Stale browser code cannot enable tournament control without
declaring support for native chip units.

On a table move, finish or detachment the worker marks old requests failed,
disables their controls and expires queued actions. Publication also enforces
the binding atomically against the first persisted snapshot. The old snapshot is
kept for reference; that window stops polling and asks the user to open a new
live view. The new table starts with automatic play and manual control off.
An action already sent is never replayed on the new table.

No schema change is needed: the initial LiveTableSnapshot stores the table
binding, and Entry.PlayTableId verifies current ownership. Deploy the backoffice
before the signed PokerController release. Older workers keep tournament control
disabled. Update both managed applications through the normal rollout; PDecision
itself needs no code change.
