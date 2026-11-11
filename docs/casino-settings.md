# Customer and poker-site strategy settings

Open **Setup > Strategy settings** for the selected customer's site. The key in
`dbo.CasinoSettings` is `(CustomerId, Casino)`, with a foreign key to `dbo.Customer`.
Operators edit only their own customer/site row; viewers are read-only. Casino
and customer keys come from authorization context and cannot be supplied by the
browser. Optimistic concurrency checks and before/after auditing remain in place.

Defaults for each newly enabled customer/site are:

- `UseHelp = 0`
- `ProfileVsHumans = Everyone`
- `ProfileMaxStake = NULL`
- `ProfileInTournaments = 1`
- `HelpMinBigBlind = NULL`, `HelpVsHumans = Everyone`, `ProfileMinBigBlind = NULL`, no listed players

## Conditions for card sharing and account profiles (migration 019)

Each feature can be limited further. A customer sets them on the same page:

| Setting | Card sharing | Account profiles against humans |
|---|---|---|
| Minimum big blind (table currency, ring games only; empty = every stake) | `HelpMinBigBlind` | `ProfileMinBigBlind` |
| Only in hands with a listed player | `HelpVsHumans = ListedPlayers` | `ProfileVsHumans = ListedPlayers` |
| Player list | `dbo.CasinoSettingsPlayer`, `Feature = CardSharing` | `dbo.CasinoSettingsPlayer`, `Feature = Profile` |

Example: card sharing On, minimum big blind 4, only hands with listed players `player1`, `player2`, `player3`.
Card sharing is then used only at ring tables with a big blind of at least 4 and only while one of those players
is still in the hand. In tournaments the minimum big blind is ignored, because tournament blinds are chips.

Names are compared the same way as `dbo.BotWinner` names (`StrategyUtil.ConvertName`, ignoring case). The list
of each feature is saved together with the settings and is part of the optimistic-concurrency version. A
"listed players" mode with an empty list is rejected (card sharing only while it is On). Account profiles at
tables without humans are unaffected by these conditions, as before.

PDecision 1.0.0.49 reads the new columns (`CasinoSettings_List` returns them after the original five) and the
lists (`CasinoSettingsPlayer_List`). Older builds ignore the new columns, but cannot parse
`ProfileVsHumans = ListedPlayers`: their refresh then keeps the previous values, and at startup they fall back
to the built-in rules. Roll PDecision 49 out to every PC of a customer before choosing that option.

Inserting/updating `scheduler.Site` or activating a `dbo.CustomerMachine`
registration initializes the pair if missing. `SchedulingEnabled` pauses traffic;
it does not revoke the configured site or reset its settings. Re-enabling a site
or adding another PC preserves any existing edits. New customers get rows as
soon as each site is configured, including sites with no machine yet. Provisioning
SQL can also call `dbo.CasinoSettings_Initialize @CustomerId, @Casino` explicitly.
Machine and site inserts that return identity values must use `OUTPUT ... INTO`
or `SCOPE_IDENTITY()`, because initialization is implemented with database triggers.

Backoffice migration `013_customer_casino_settings.sql` archives the old shared
rows privately in `dbo.CasinoSettingsLegacy`, maps existing enabled customer/site
pairs and backfills missing pairs. Existing customer pairs retain legacy values
for their casino; pairs without a previous shared row receive the defaults above.
The migration never creates customerless settings rows.

PDecision 1.0.0.41 sets its settings scope from the machine registration's customer
ID and casino. Startup and periodic refresh both pass that scope to
`CasinoSettings_List`. Cache snapshots are tagged with the customer ID so a
context change cannot reuse another customer's settings. A refresh failure keeps
the current customer's cached values. Settings refresh normally takes up to ten
minutes after all applicable PCs have received version 41.

For compatibility during rollout, `CasinoSettings_List` with no customer ID
returns fixed defaults rather than any customer's configured values. Legacy
PDecision instances therefore cannot accidentally read a different customer's
row; custom customer values require version 41. Maintenance writes through
`CasinoSettings_Upsert` require `@CustomerId` and reject an omitted customer.

Deploy the schema migration, Backoffice API/frontend, then the signed PDecision
41 application release. New installations should use the updated
`PDecision/sql/CasinoSettings.sql` after `CustomerMachines.sql`.
