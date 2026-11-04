# Live card sharing

When Strategy settings > Card sharing (`dbo.CasinoSettings.UseHelp`) is on for
the selected customer and site, live view displays the other active bots' hole
cards. The live table heading reports how many other bots' cards are shown.
It applies to ring, SNG and MTT tables and works across PCs.

The API requests short-lived live snapshots from the bots seated at that table,
using the existing worker telemetry. It reads only each source bot's own cards.
Cards are merged only when the physical table, hand, board, game, seat and player
identity match. Both snapshots must be no older than ten seconds. A bot's cards
may take a telemetry cycle to appear. Human cards remain hidden unless shown
normally at showdown.

The API checks the customer/site setting on every poll. Turning it off stops
sharing immediately on the next successful poll. Helper telemetry leases expire
within 45 seconds after the window closes or sharing is disabled. They do not
enable manual control or change the bots' decisions.

This feature needs only a backoffice deployment; no machine release, database
migration or process restart is required.

Validation: `python -m pytest tests/test_live_cards.py`; with the local preview
on port 4298, `python tools/check_live_cards.py` checks the real card renderer.
