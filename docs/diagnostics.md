# AI diagnosis: local first

The Backoffice **AI diagnosis** page accepts operational questions for the selected
EvenBet or BluffPoker site. Requests and answers are private to the authenticated
provider, user, customer and site. The latest 50 investigations are listed, grouped
with their follow-up questions. Investigations inactive for 90 days are removed
on service startup as complete threads. History lives in
`artifacts/diagnostics/history.sqlite3`, outside Git. Protect it as customer data.

The agent cannot edit code or settings, register bots, move funds, request log
collection, restart a worker, or execute arbitrary SQL. It explains confirmed,
probable and unknown causes and cites the evidence collected. There is no shell,
browser, SQL execution or general-purpose HTTP tool exposed to the model.

## Run on this PC

From the PokerBackoffice repository:

```powershell
python -m venv diagnostics/.venv
diagnostics/.venv/Scripts/python.exe -m pip install -r diagnostics/requirements.txt
```

Configure `OPENAI_API_KEY` privately in your Windows user environment or current
PowerShell process. Do not put it in chat, frontend code, Git or screenshots.
Existing Backoffice SQL settings are reused (`BACKOFFICE_SQL_*`, or the legacy
local `SqlConnectionString`). The launcher also reads the Windows user API-key
setting when the process environment does not have it.

```powershell
./tools/start_diagnostics.ps1 -Mode live -CustomerId 14004
```

Open `http://127.0.0.1:4280/backoffice#diagnostics`. Customer 14004 has EvenBet and
BluffPoker sites; customer 3 selects the Simo workspace. The local preview bypasses
Microsoft login for its fixed local user and customer: never deploy that server.
Ctrl+C stops the preview and its worker. Both servers bind to loopback. The
launcher generates an ephemeral private broker token, never sent to the browser.

To keep Nenad and Simo open together on this PC, run:

```powershell
./tools/start_diagnostics.ps1 -Mode live -CustomerId 14004 -AdditionalCustomerIds 3
```

Nenad opens on port 4280 and Simo on port 4281. Both use the same private diagnostic
worker, with separate fixed customer contexts and isolated request histories.
Additional previews stop with the launcher. These loopback developer previews do
not replace production Microsoft authentication.

To exercise the page, job processing and persistent history without model charges:

```powershell
./tools/start_diagnostics.ps1 -Mode recorded -CustomerId 14004
```

Recorded mode uses a small demonstration fixture and a deterministic answer,
explicitly labelled on the page. It does **not** test real model reasoning or live
diagnostic data. The surrounding existing workspace still reads real customer data.
Live mode fails startup when no API key is configured; it never silently falls back
to a fixture. Model: `POKERFILL_DIAGNOSTICS_MODEL` (default `gpt-6.2-sol`).

## Follow-up questions

After an answer, the form switches to **Ask follow-up**. Earlier questions and
answers remain together in the investigation, including after a page reload.
Open an investigation from **Your requests** to continue it later. Choose
**New investigation** for an unrelated question with no previous dialogue attached.
The example-question buttons also start new investigations.

Each follow-up includes the original question/diagnosis and up to three recent
question/answer exchanges, with a 16,000-character context bound. Long context is
compacted while preserving the original and most recent exchanges as anchors.
A label under the answer shows how many earlier
exchanges were included. The full thread stays readable; a thread can contain
at most twenty questions. Earlier evidence details are loaded on demand.

The agent sees prior diagnoses as historical conversation, not current proof.
Follow-ups start with this dialogue and call operational tools when fresh evidence
is needed. New investigations retain the fixed schedule/health/lobby baseline.
Each answer has its own evidence references, timestamps and model usage. Follow-ups
are billable model requests and count toward the existing request limits.

Existing standalone requests become single-question investigations automatically;
their original answers and raw evidence are preserved. The local SQLite migration
is additive and does not require a PC update or an Azure SQL migration. A parent
request must belong to the same user, customer, site and identity provider. Pending
answers cannot be followed up, and a follow-up must extend the latest answer to
avoid competing branches.

If a model request fails because OpenAI API credits are exhausted, the failed
question stays in the thread and earlier answers remain readable. The page shows
the provider-credit problem explicitly. After restoring API credits, open that
investigation and retry the question as a follow-up; a failed attempt can be
continued. Temporary provider throttling is reported separately. Raw provider
messages, API keys and connection details are not shown.

## Components and bounds

* `frontend/diagnostics-ui.js`: questions, status polling, escaped answers and history.
* `api/backoffice/diagnostics.py`: authenticated SWA broker. It checks membership
  and site access before deriving scope; browser-supplied identities are ignored.
* `diagnostics/service.py`: private FastAPI worker, bounded serial job queue,
  idempotent request IDs and customer/user-scoped SQLite conversation history.
  `diagnostics/conversations.py` bounds the prior dialogue included with follow-ups.
  Interrupted jobs become visibly failed
  on restart. One service process only in this local version.
* `diagnostics/agent.py`: LangGraph baseline or conversation context → bounded LangChain tool loop →
  structured report → evidence-reference validation. Up to three model/tool rounds,
  twelve evidence calls, bounded output, 60,000 aggregate estimated token reservation
  plus actual-usage checks. Estimates include output allowance, but provider token
  accounting can differ; this is not a billing hard limit. Each model call has a
  40-second timeout and one retry. A four-minute investigation budget is checked
  before each new tool/model step; an in-flight network call can finish after that
  boundary. At most two pending requests and ten per hour per
  user/site; ten queued jobs globally.
* `diagnostics/data.py`: parameterized SELECTs and existing read-only helpers.
  Every tool checks customer/site ownership independently and rolls back/closes
  its SQL connection. A SELECT-only adapter also rejects writes and stored-procedure
  execution. Tool names and query templates are fixed. Lobby, command, timeline
  and tournament row queries retain at most 100 rows. Schedule reconstruction
  reads entry intervals only within a bounded lookback; configuration and aggregate
  queries return their existing bounded domain. Model evidence lists retain at most
  24 items with truncation noted.

Tools cover current schedule compliance, historical drops, site constraints and
exclusions, machine health, stale/live lobby evidence, account eligibility and
cooldowns, funding snapshot coverage, command outcomes, SNG/MTT plans and entries,
incident timelines, and existing machine-log signals. Historical lookbacks are
bounded to seven days (schedule charts use whole local dates). Reports identify
missing coverage and do not treat empty/truncated results as proof of absence.

Log analysis downloads only existing, ready, unexpired, customer/site-scoped
archives. It checks manifest scope and archive size and returns allowlisted error
counts from controller logs. It never returns raw log lines, PDecision hand logs,
credentials, tokens, SAS URLs or account names. Counts are not distinct incidents
and archive tails may not cover the entire requested period.

## Wallet telemetry

`ScheduleController/sql/045_account_diagnostics.sql` and the worker's optional
`account_diagnostics.py` provide safe balance snapshots from **existing owned
sessions only**. Local tests do not install the migration or deploy workers.
Telemetry is disabled by default. Enable `scheduler.Site.AccountDiagnosticsEnabled`
for a specific site after a separately authorized rollout; the environment override
`POKERFILL_ACCOUNT_DIAGNOSTICS=1` enables it for all sites in that worker. Samples are five
minutes apart. After the final table/registration closes, the worker stops periodic
sampling, waits for any in-flight diagnostic SQL write, captures a final balance,
persists it, and then closes the connection. Optional telemetry failures do not
prevent logout. A failed read updates the attempt status while preserving the last
successful balance, source and observation timestamp.

The publisher checks the worker epoch and account lease. When the final entry has
already released its lease, a logout snapshot additionally requires a matching
open/recently closed session, no active competing lease and no other active session
owner. Idle snapshots remain readable after the worker stops. The funding tool
includes every enabled, active, non-synthetic account, including accounts with no
snapshot, and groups known logout balances, provisional session samples, stale
balances and missing/failed evidence. The 24-hour stale threshold describes cache
age; even a recent logout snapshot is not a guarantee of present funds.

BluffPoker reads the existing bearer directly and never calls the refresh/login
path. Native integer `available` values are retained without inventing a fiat
conversion. EvenBet requests GetBalance on the existing WebSocket. Its vendor
client maps BalancesUpdate `cashInfoList[].mt` to money type and `.ma` to the
integer wallet amount; those allowlisted values are saved in `WalletsJson`, keeping
different money types separate. Bonus money is excluded. The monetary-field
mapping is verified against the [vendor client](https://demo.evenbetpoker.com/),
including the vendor DTO's zero defaults when the server omits a zero amount.
The live wire format was checked on a canary PC without logging monetary values
or account identities. The first sample waits 15 seconds after login for lease
adoption during restart reconciliation.
Money-type-to-fiat mapping remains unverified: do not sum money types or compare
them with fiat buy-ins without that conversion. An unrecognized response records
`balance_shape_unverified`. Failed/expired reads
remain unknown or retain clearly labelled older evidence. Accounts accumulate
logout snapshots as they run; accounts never observed remain unknown. Pending
settlements, deposits, withdrawals or external activity can change cached balances.
The funding tool works before the
migration and explicitly reports that telemetry is missing.

## Validation

```powershell
diagnostics/.venv/Scripts/python.exe -m pip install pytest httpx
diagnostics/.venv/Scripts/python.exe -m pytest tests/test_diagnostics.py tests/test_diagnostic_conversations.py tests/test_diagnostic_log_signals.py -q
.venv/Scripts/python.exe -m pytest tests -q
.venv/Scripts/python.exe tools/check_diagnostics_browser.py
```

For real model requests, load the saved key into this PowerShell process without
printing it, then select live mode explicitly:

```powershell
$env:OPENAI_API_KEY = [Environment]::GetEnvironmentVariable('OPENAI_API_KEY', 'User')
.venv/Scripts/python.exe tools/check_diagnostics_browser.py --mode live
```

This test makes two billable investigations against the local user's EvenBet and
BluffPoker sites. It checks successful completion, actual token usage, evidence
references, persisted answers after reload and desktop/mobile rendering. Results
and screenshots stay under ignored `artifacts/diagnostics/`. On 2026-11-19 both
investigations passed and used 66,810 aggregate model tokens. This is an initial
integration smoke test, not a complete diagnostic-accuracy benchmark. It neither
deploys workers nor installs wallet telemetry.

Browser QA requires the existing Backoffice Playwright environment and local SQL
access. It starts/stops its own loopback servers, uses a separate test-history
database (default test ports 4380/4410), exercises both platform site selections,
follow-up context and grouped history, request/answer/reload history,
loading an older answer's evidence, starting an independent investigation,
HTML escaping (recorded mode) and mobile layout, and writes screenshots to
`artifacts/diagnostics/`. Default recorded mode sends no real model requests. Neither mode performs fleet or
production database writes. Worker tests live in
`ScheduleController/tests/test_account_diagnostics.py`.

## Azure stage two

Do not deploy this local SQLite/in-memory queue service as a production backend.
Keep the SWA authenticated broker, replace local jobs with an Azure Storage Queue
and a Container Apps worker, and store history/results in customer-scoped SQL/Blob
storage. Use managed identity and Key Vault, a dedicated SQL reader with narrowly
granted diagnostic views, database-enforced tenant separation or separately scoped
credentials, durable claim/idempotency/retry/dead-letter handling, request auditing,
retention and per-customer spend limits. No model provider tracing is enabled by
this implementation; enabling LangSmith would be a separate customer-data decision.

Production API requests should enqueue/poll quickly and never wait for a model
investigation. The local broker contract already uses that pattern. The private
service token is an interim local mechanism, not the intended Azure identity model.

Before Azure rollout, verify real-model diagnoses against recorded incidents on
both platforms, finish the EvenBet money-type-to-fiat mapping, and review the reader identity,
permissions, retention and cost limits. Existing broad local SQL credentials are
convenient for local tests but are **not** a production read-only identity merely
because tools execute SELECTs and roll back.

Implementation references: [LangGraph quickstart](https://docs.langchain.com/oss/python/langgraph/quickstart)
and [ChatOpenAI tool calling and structured output](https://docs.langchain.com/oss/python/integrations/chat/openai).


## Customer-PC log evidence

The local live launcher enables `POKERFILL_DIAGNOSTICS_COLLECT_LOGS=1`.
For an operator's question or follow-up, the authenticated broker requests diagnostic
bundles from active PCs assigned to the selected customer/site, reusing collections
requested within 15 minutes and coalescing pending requests. Viewer requests never
queue collections. The worker waits up to 45 seconds for pending collections before
continuing; an offline PC does not block a diagnosis indefinitely. Collection does
not restart applications, log accounts in, or change play. It is audited through
the existing machine-log API. Requests remain diagnosis-only; the model has no write tool.

`get_worker_log_signals` inventories up to 24 scoped PCs and reads one machine archive
per call. Select `machine_id`, `topic` (restart/authentication/funding/connectivity/all)
and optionally `around_utc`, an ISO timestamp with an explicit offset. It extracts
only known operational event codes, timestamps, startup exit codes and file coverage
from controller, updater and PDecision logs. Raw lines, hand data, account identities,
paths, secrets and free-form exception messages are not sent to the model. Worker
lines explicitly tagged for another site are excluded; untagged machine events have
unconfirmed site attribution. Shared-PC bundles must match the archive site manifest.
UTC events are narrowed to one hour either side of the incident. New collectors record the PC IANA timezone so worker timestamps can be converted to UTC. Ambiguous DST times remain unverified. Without that metadata, unzoned PC timestamps
are retained from adjacent dates and labelled unverified; their order does not prove
UTC correlation. Lists are bounded and lifecycle events take priority over generic errors.
The incident timeline also includes scoped deployment timestamps.

Installed collectors through 1.0.20 return at most 8 MiB per file and 48 MiB total.
The prepared 1.0.21 collector streams complete retained application files up to
128 MiB each and 512 MiB total before compression, retaining the 64 MiB compressed
upload limit. Larger files remain bounded tails, and all omitted/truncated coverage
is reported in the archive manifest. It includes only registered PokerSuite log
locations, not arbitrary customer documents or configuration files. A normal signed
PC release is required to install that collector; changing the local agent does not
upgrade customer PCs. The built collector is not a fleet deployment.
