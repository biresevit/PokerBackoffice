# Casino strategy settings

Open **Setup > Strategy settings** for the selected site. Operators can edit
`UseHelp`, `ProfileVsHumans`, `ProfileMaxStake` and `ProfileInTournaments` in
`dbo.CasinoSettings`. Viewers can inspect the values but cannot save.

The casino key comes from the authorized `scheduler.Site`; the request cannot
choose another casino. These settings are casino-wide. If different customers
share a casino, customer editing is disabled and a main administrator must
manage its global settings. The existing BluffPoker row is separate from Evenbet.

No row is created on page load. Until saved, existing built-in PDecision rules
continue to apply. Evenbet's initial form values match its built-in defaults:
card sharing off, profiles against everyone, all stakes and tournaments on.
Saving creates the Evenbet row; it never edits BluffPoker.

Saves validate all values, check a fingerprint of the loaded database row to
prevent lost edits, and record before/after values in the audit log. Existing
PDecision instances read settings during their normal database refresh (default
10 minutes). No worker release or PDecision restart is needed.

Apply backoffice migration `011_casino_settings_grants.sql` before deploying the
website. It grants the existing restricted API user SELECT/INSERT/UPDATE on
`dbo.CasinoSettings`; it does not seed or change any setting.
