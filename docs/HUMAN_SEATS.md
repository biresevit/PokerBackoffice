# Human-seat history

Overview displays the latest valid ring human-seat count beside bot entries and
adds a purple human-seat series to the ring history chart. Monitoring shows hourly
averages, ranges and sample coverage on a separate count scale. Each street's
hover readout includes the corresponding hourly human count.

The Azure ScheduleController `human_seat_history_tick` runs once a minute,
independently of scheduling. It calls `backoffice.SampleHumanSeats`, installed by
`sql/021_human_seat_history.sql`. Set `HUMAN_SEAT_HISTORY_ENABLED=enabled` on that
Function App after applying the migration. No PC software update is needed.
The Backoffice SQL principal has SELECT only on the sample table; the scheduler
principal has EXECUTE on the collector procedure. The collector stores counts,
not player names.

## Meaning and coverage

- A human seat is an observed seat outside the site's managed bot account list.
  Account IDs and site-scoped usernames identify managed bots. External bots
  cannot be distinguished from humans by this definition.
- These are seats, including sitting-out players, not unique people or people
  who necessarily received a hand during that minute.
- The site scope counts each open ring table once. A PC scope counts each ring
  table with an open seated bot entry on that PC once. Shared tables appear in
  each relevant PC scope, but only once in the site scope.
- Only complete seat lists, fresh within 180 seconds, with a current ready
  observer epoch and heartbeat qualify. Unknown identities, stale observers,
  missing tables, incomplete seat lists and missing samples stay unknown.
  When some tables are fresh but full site coverage is unavailable, the UI shows
  their observed human seats as a lower bound (`≥`) and reports partial coverage.
  This matters because the lobby retains old open-table inventory records.
- History starts at enablement. It cannot establish human counts for older
  incidents. Tournament registration counts do not identify humans, so SNG and
  MTT human counts are unavailable.
- Historical chart values average valid samples in their minute/hour bucket.
  Unknown samples are excluded, rather than treated as zero. Monitoring includes
  valid and received sample counts; its decision metrics include all formats.
  The date and PC filters scope human history; the opponent filter scopes
  decision metrics only.
- Correlation with human presence does not prove that the solver was invoked or
  caused a delay. Per-decision solver telemetry would be needed to establish that.

## Verification

Run `python -m pytest -q tests`, `python tools/check_monitoring_browser.py`,
and `python tools/check_human_seat_sql.py`. The last command uses the local SQL
connection but exercises only temporary fixture tables, leaving customer data
unchanged. ScheduleController has transaction/error handling tests for its sampler.
