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
