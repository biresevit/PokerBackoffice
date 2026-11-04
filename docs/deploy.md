# Deploying the poker bot fleet

How to ship a change to production: which component a change belongs to, how to test it, the exact commands, the order they must run in, and how to verify the result.

All paths are relative to the workspace root `C:\Users\bires\projects\bot`, which contains one git repository per component. The workspace root itself is not a repository. All commands are PowerShell on the development PC, which has the Azure login, database access and the release signing key.

## 1. Components

| Component | Repository / source | Runs on | Ships with |
|---|---|---|---|
| Database schema (`scheduler.*`, `dbo.*`) | `ScheduleController/sql/NNN_*.sql` | Azure SQL | §4 Migrations |
| Database schema (`backoffice.*`) | `PokerBackoffice/sql/NNN_*.sql` | Azure SQL | §4 Migrations |
| Scheduler function app `poker-schedule-controller` | `ScheduleController` (`function_app.py`, `cloud_scheduler.py`, `planner.py`, `rules.py`, `update_rollouts.py`, `hand_history_results.py`) | Azure Functions, 30 s timer | §5 |
| Backoffice web app and API (Static Web App `poker-control-nenad`) | `PokerBackoffice/frontend`, `PokerBackoffice/api` | Azure Static Web Apps | §6 |
| PC worker (PokerController) | `PokerController/poker_controller/*` **and** `ScheduleController/schedule_controller/pilot*.py`, `manual_worker.py`, `chat_worker.py` | every bot PC | §7 PC release |
| PDecision (decision service) | `PDecision` repo (C#) | every bot PC, port 5005 | §8, then §7 |
| Updater agent and PokerSuite Setup | `PokerController/updater` | every bot PC | §9 (rare) |

### Which deploy does my change need?

The same Python package `ScheduleController/schedule_controller` ships in three places. Check every file you changed:

| Changed file | Function app (§5) | Backoffice (§6) | PC release (§7) |
|---|---|---|---|
| `schedule_controller/cloud_scheduler.py`, `hand_history_results.py`, `function_app.py` | yes | | |
| `schedule_controller/planner.py` | yes | | |
| `schedule_controller/rules.py`, `update_rollouts.py` | yes | yes (bundled copy, used by the updates API) | |
| `schedule_controller/hand_settlement.py` | yes | yes (bundled copy, used by the hand-history views) | |
| `schedule_controller/pilot.py`, `pilot_repository.py`, `manual_worker.py`, `chat_worker.py` | | | yes |
| `PokerController/poker_controller/*` | | | yes |
| `PokerBackoffice/api/*`, `frontend/*` | | yes | |
| `ScheduleController/sql/*`, `PokerBackoffice/sql/*` | | | migration (§4) |
| `PDecision/*` | | | §8 then §7 |

The backoffice keeps a copy of the shared scheduler files in `PokerBackoffice/api/schedule_controller` with checksums in `api/scheduler-core.json`. `tools/deploy.py` refreshes that copy automatically (it runs `tools/build.py`). Commit the refreshed copy together with the backoffice change.

## 2. Ground rules

- **Never paste or commit connection strings, passwords, tokens or SAS URLs.** The tools read them from environment variables, Azure app settings and the Windows user profile; keep it that way.
- **Order:** schema first, then the code that reads it. The backoffice, the scheduler function and the PC worker all fail on a missing column. Old code must keep working with the new schema (add columns with defaults; do not rename or drop in the same release).
- **Read-only checks are safe at any time.** Database writes, deploys, release publishing and rollouts are production changes: an agent does them only when the owner has asked for that deploy.
- **Test a new PDecision or PC build on an isolated port, never on the live PDecision port 5005** of a PC that is playing.
- Production PCs only change through signed releases and rollouts (§7). Do not copy files onto a bot PC.
- Commit to `main` in each repository before deploying, so production always matches a commit. End commit messages with the attribution line your session requires.

## 3. Tools, environments and access

| Item | Location |
|---|---|
| ScheduleController Python env (tests, migrations, wheel build) | `ScheduleController\.venv` |
| PokerController Python env (tests, PyInstaller) | `PokerController\.venv` |
| Backoffice Python env (tests, deploy, publish) | `PokerBackoffice\.venv` |
| Azure CLI (only here) | `PokerBackoffice\.azure-venv` → `.\.azure-venv\Scripts\python.exe -m azure.cli ...` |
| Node and Static Web Apps CLI used by the backoffice deploy | `PokerBackoffice\artifacts\tooling` (installed by `tools\setup_node.py`) |
| Release signing private key | `%LOCALAPPDATA%\PokerSuitePublisher\release-signing.pem`. Every updater agent trusts its public key. Never regenerate or move it; back it up privately. |
| Resource group / subscription | `poker-backoffice` / the subscription in `tools\configure_azure.py` |

Database credentials come from environment variables on the development PC:

- Migrations and ScheduleController tools: `SCHEDULE_SQL_CONNECTION_STRING` (ODBC) or `SqlConnectionString` (ADO.NET).
- Backoffice tools and API: `SqlConnectionString` or `BACKOFFICE_SQL_*`.

The Azure CLI must be logged in (`.\.azure-venv\Scripts\python.exe -m azure.cli login`) for §5, §6 and §7.

A common mistake: `python -m schedule_controller.database` only works from `ScheduleController` with its own `.venv`; `python -m azure.cli` only works with `.azure-venv`.

## 4. Database migrations

Migrations are numbered SQL files applied once, in order, inside one transaction, and recorded with their SHA-256 in `scheduler.SchemaMigration` / `backoffice.SchemaMigration`. An applied file must never be edited (the runner refuses a changed checksum); add a new numbered file instead. `GO` lines split batches; put `ALTER TABLE ... ADD` and any statement that uses the new column in separate batches.

Write migrations so they can be re-run safely (`IF COL_LENGTH(...) IS NULL`, `IF OBJECT_ID(...) IS NULL`) and give new `NOT NULL` columns a default.

### Scheduler schema (`ScheduleController/sql`)

```powershell
cd C:\Users\bires\projects\bot\ScheduleController
.\.venv\Scripts\python.exe -m schedule_controller.database          # validate: applies pending files, prints them, rolls back
.\.venv\Scripts\python.exe -m schedule_controller.database --apply  # commit
```

The validate run must list exactly the files you expect, followed by "Validated and rolled back; database unchanged."

### Backoffice schema (`PokerBackoffice/sql`)

```powershell
cd C:\Users\bires\projects\bot\PokerBackoffice
.\.venv\Scripts\python.exe tools\admin.py migrate           # validate and roll back
.\.venv\Scripts\python.exe tools\admin.py migrate --apply
```

### New tables need permissions

The scheduler function and the backoffice API log in as restricted SQL users with per-table grants. A new **column** needs nothing. A new **table** must be granted to the user that reads or writes it:

- scheduler: add it to the `grants` map in `ScheduleController\tools\configure_function.py`;
- backoffice: see `PokerBackoffice\tools\configure_azure.py`.

Then run the tool, or apply the equivalent `GRANT` in a migration. Without it the code fails with a permission error only in production; the tests pass.

### Trying a migration without committing

To try a single new file against production data, run it in a transaction that always rolls back:

```python
import pyodbc, re
from schedule_controller.database import connection_string
sql = open(r"sql\NNN_name.sql", encoding="utf-8").read()
conn = pyodbc.connect(connection_string(), autocommit=False); c = conn.cursor()
try:
    c.execute("SET LOCK_TIMEOUT 3000")
    for batch in re.split(r"(?im)^GO\s*$", sql):
        if batch.strip(): c.execute(batch)
    # SELECT the affected rows here and inspect them
finally:
    conn.rollback(); conn.close()
```

## 5. Scheduler function app (`poker-schedule-controller`)

The function runs `CloudScheduler` every 30 seconds (planning joins and leaves, rollouts, session expiry) and the hand-history processor. Its package is a zip of `function_app.py`, `host.json`, `requirements.txt` and a wheel of `schedule_controller`; Azure installs the wheel at deploy time.

1. Test:
   ```powershell
   cd C:\Users\bires\projects\bot\ScheduleController
   .\.venv\Scripts\python.exe -m pytest -q
   ```
2. Build the package (use a new folder name per build, `artifacts\azure-function-<date>-<topic>`):
   ```powershell
   $name = "azure-function-20261101-example"
   $dir = "artifacts\$name"
   New-Item -ItemType Directory -Force $dir | Out-Null
   Copy-Item function_app.py, host.json, requirements.txt $dir
   .\.venv\Scripts\python.exe -m pip wheel . --no-deps -w $dir
   Compress-Archive -Path "$dir\*" -DestinationPath "artifacts\poker-schedule-controller-$($name.Substring(15)).zip" -Force
   ```
   `requirements.txt` references `./schedule_controller-0.1.0-py3-none-any.whl`. The zip must contain exactly these four files at its root.

   Check that the zip really contains your change, for example:
   ```powershell
   .\.venv\Scripts\python.exe -c "import zipfile,sys; w=zipfile.ZipFile(sys.argv[1]); print('YOUR_MARKER' in w.read('schedule_controller/planner.py').decode())" "$dir\schedule_controller-0.1.0-py3-none-any.whl"
   ```
3. Deploy (note `.azure-venv`):
   ```powershell
   cd C:\Users\bires\projects\bot\PokerBackoffice
   .\.azure-venv\Scripts\python.exe -m azure.cli functionapp deployment source config-zip --resource-group poker-backoffice --name poker-schedule-controller --src "C:\Users\bires\projects\bot\ScheduleController\artifacts\poker-schedule-controller-<topic>.zip" -o json
   ```
4. Verify that the timer runs: `scheduler.Site.LastReconciledUtc` keeps moving forward (every ~30 s), and new `scheduler.Command` rows behave as intended (§10). If the planner shipped a change in behaviour, watch the next few joins.

Rollback: redeploy the previous zip from `ScheduleController\artifacts` (they are kept by date and topic).

If the bundled shared files also changed (`rules.py`, `update_rollouts.py`, `hand_settlement.py`), deploy the backoffice as well (§6).

## 6. Backoffice (Static Web App `poker-control-nenad`)

Frontend (`PokerBackoffice/frontend`, plain ES modules, no build step) and the managed Python 3.11 API (`PokerBackoffice/api`) deploy together.

1. Test:
   ```powershell
   cd C:\Users\bires\projects\bot\PokerBackoffice
   .\.venv\Scripts\python.exe -m pytest -q
   ```
   Most database tests are skipped without a test database; anything that touches a changed SQL query should also be exercised read-only against production (see §10 for the pattern: construct `Store`/a service object with a viewer context and call the method).
2. Check JavaScript syntax. There is no Node on PATH; use VS Code's runtime:
   ```powershell
   $env:ELECTRON_RUN_AS_NODE = '1'
   Copy-Item frontend\app.js $env:TEMP\check.mjs -Force
   & "$env:LOCALAPPDATA\Programs\Microsoft VS Code\Code.exe" --check "$env:TEMP\check.mjs"; $LASTEXITCODE   # 0 = parses
   ```
   Repeat for every changed module (`manual-controls.js`, `updates-ui.js`, `chat-ui.js`, ...).
3. **Bump cache versions** for anything changed, or browsers keep the old file:
   - `frontend/index.html`: `app.js?v=...` and `fixes.css?v=...`;
   - `frontend/app.js`: the `?v=` on each changed imported module (`manual-controls.js`, `updates-ui.js`, ...).
4. Deploy (bundles the shared scheduler files, packages the API dependencies for Linux, uploads with the SWA CLI):
   ```powershell
   .\.venv\Scripts\python.exe tools\deploy.py
   ```
   Success ends with `Project deployed to https://lively-rock-032158003.4.azurestaticapps.net`.
5. Verify: the site serves the new versions, e.g.
   `curl -s https://lively-rock-032158003.4.azurestaticapps.net/ | Select-String 'app.js\?v='`, then open the changed pages. A generic "The request could not be completed" page means the API raised; reproduce the call read-only (§10) to get the traceback, because the API has no Application Insights.

Rollback: check out the previous commit of `PokerBackoffice` and run `tools\deploy.py` again.

## 7. PC release (PokerController worker + PDecision)

A release is an immutable, signed zip containing both PC applications: PokerController (PyInstaller folder) and PDecision (obfuscated `dist`). Updater agents on the PCs download, verify, install and health-check it when a rollout reaches them.

1. Test:
   ```powershell
   cd C:\Users\bires\projects\bot\PokerController
   .\.venv\Scripts\python.exe -m pytest -q
   cd ..\ScheduleController
   .\.venv\Scripts\python.exe -m pytest -q
   ```
   Known: `PokerController\tests\test_manual.py::test_manual_action_never_retries_ambiguous_network_send` fails in the PokerController venv because `schedule_controller` is not installed there; it is unrelated to releases.
2. Build PokerController. This bundles `poker_controller` **and** `schedule_controller` from the working tree, so both repositories must be at the commits you intend to ship:
   ```powershell
   cd C:\Users\bires\projects\bot\PokerController
   .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --onedir --name PokerController --distpath artifacts\fleet-package --workpath artifacts\fleet-build --specpath artifacts --paths ..\ScheduleController --collect-submodules poker_controller --collect-submodules schedule_controller --add-binary "artifacts\updater-agent\PokerSuite.Updater.exe;diagnostics-agent" updater\worker_entry.py
   ```
   It must end with `Build complete!`; the output is `artifacts\fleet-package\PokerController`. Check that `_internal\diagnostics-agent\PokerSuite.Updater.exe` is there: the worker starts the machine-diagnostics collector from it, and a release without it is about 31 MB instead of about 59 MB.
3. Publish:
   ```powershell
   cd C:\Users\bires\projects\bot\PokerBackoffice
   .\.venv\Scripts\python.exe tools\publish_release.py --label <label> --pdecision-version <version> --controller-version <version>
   ```
   - `--label`: `YYYY.MM.DD.N`, unique and immutable (the tool refuses an existing label). Use the next free `N` for the day. To see existing labels, query `scheduler.UpdateRelease` ordered by `PublishedUtc`.
   - `--pdecision-version`: the version of the PDecision build in `PDecision\obfuscation\dist` (the `<FileVersion>` in `PDecision\PDecision\PDecision.csproj`, e.g. `1.0.0.34`). **Always pass it explicitly**; the tool's default is outdated. If PDecision did not change, use the version of the previous release (see its manifest in `scheduler.UpdateRelease`).
   - `--controller-version`: `0.1.0+<short commit of PokerController or ScheduleController>.<topic>`, e.g. `0.1.0+926e29e.show-cards`. The PC reports it back; it is how you tell what a PC runs.
   - Output: `{"release": ..., "id": ..., "package_mb": ..., "sha256": ...}`.
4. Roll out from the backoffice **Updates** page:
   - choose the release;
   - Start: **Now** or a set time;
   - **Wait for sessions to finish** (default: drains one PC at a time, no traffic is cut off) or **Update immediately** (force-stops every selected PC at once, mid-hand; the PCs restart in about 1–2 minutes);
   - select the PCs (**Select all** selects every PC whose updater is connected).

   Cancel an older paused or running rollout first, so only one is active.
5. Verify: each rollout task reaches `completed`; under Machines each PC reports the new PokerController/PDecision versions and is Online; traffic recovers (§10). A failed start rolls back automatically to the previous pair and pauses the rollout: read the task's Detail on the Updates page.

### Updater agent versions

An application rollout does not upgrade the updater agent itself. Some rollout features need a minimum agent version: Immediate updates need agent 1.0.13 to force-stop, and older agents fall back to draining. A PC on an old agent is upgraded by rerunning PokerSuite Setup on it (§9).

## 8. PDecision

Only needed when the `PDecision` repository changed.

1. Bump `<FileVersion>` and `<AssemblyVersion>` in `PDecision\PDecision\PDecision.csproj`. The previous release commits are named `Release PDecision 1.0.0.N`.
2. Build the obfuscated delivery as described in `PDecision\obfuscation\README.md`:
   ```powershell
   cd C:\Users\bires\projects\bot\PDecision\obfuscation
   .\build.ps1 -ObfuscarConsole <path to obfuscar GlobalTools.dll>
   ```
   Output: `PDecision\obfuscation\dist`. `DecisionMaking.dll` and `PokerUtil.dll` are never obfuscated. `work\obf-output\Mapping.txt` must stay private.
3. Test the `dist` build exactly as that README's "Testing a build" section says: reaches `ready` on `/api/health`, and the multitable test passes. Use a test port, never the live 5005 of a playing PC.
4. Check `dist\appsettings.json` before shipping, as that README's "Before shipping" section says: the restricted database login only, and hand-history upload settings as in production.
5. Commit the version bump, then ship it with a PC release (§7) using `--pdecision-version` set to the new version.

## 9. Updater agent and PokerSuite Setup (rare)

- The agent version is hard-coded in `PokerController\updater\Program.cs` (`agent_version` in `Poll`/`Report`); keep `PokerSuite.Updater.csproj` `<Version>` in step.
- Build the agent: `dotnet publish updater\PokerSuite.Updater.csproj -c Release -o artifacts\updater-agent` (from `PokerController`). Setup bundles the agent (`updater\setup\agent.zip`) and the Microsoft prerequisites (see "Building Setup with bundled prerequisites" in `docs\rolling-updates.md`).
- Publish a new initial installer: `PokerBackoffice\tools\publish_updater.py --version <version>`. New PCs download Setup from Machines → **Set up a new PC**, then the main administrator approves the pairing code there (`docs\pc-pairing-installation.md`).
- Existing PCs get a new agent only by rerunning Setup on the PC; enrollment is preserved.
- `tools\verify_updater.py` tests process replacement and rollback with fake applications; it does not cover the Immediate (`forcing`) path.

## 10. Verification queries (read-only)

Run small read-only scripts with the backoffice environment:

```python
# save as a scratch file, run: cd PokerBackoffice; .\.venv\Scripts\python.exe <file>
import sys; sys.path.insert(0, "api")
from backoffice.db import session
with session() as db:
    print(db.one("SELECT SYSUTCDATETIME() AS now"))
    print(db.one("SELECT LastReconciledUtc, NextJoinUtc FROM scheduler.Site WHERE SiteId=1"))
```

Useful checks:

| Question | Query |
|---|---|
| Is the scheduler running? | `scheduler.Site.LastReconciledUtc` advances every ~30 s |
| Recent joins/leaves and their outcome | `scheduler.Command c JOIN scheduler.Entry e ON e.EntryId=c.EntryId JOIN dbo.BotAccount b ON b.BotAccountId=e.BotAccountId` filtered on `c.CreatedUtc`; `Status`, `ResultCode`, `ResultText` |
| Open tables per PC and account | `scheduler.Entry WHERE IsOpen=1 GROUP BY MachineId, BotAccountId` |
| PC health | `scheduler.MachineAssignment` (`IsReady`, `LastHeartbeatUtc`, `MaintenanceTaskId`), `scheduler.MachineUpdateAgent` (`AgentVersion`, `CurrentReleaseId`, `Stage`) |
| Releases and rollouts | `scheduler.UpdateRelease`, `scheduler.UpdateRollout`, `scheduler.MachineUpdateTask` |
| A migration applied | `scheduler.SchemaMigration` / `backoffice.SchemaMigration` |

To debug a failing backoffice page, call the same method directly with a viewer context; it prints the real traceback:

```python
from types import SimpleNamespace
from backoffice.store import Store
store = Store(db, SimpleNamespace(customer_id=<customer id>, role="viewer", subject="x", provider="p"))
store.sessions(1, {"from": "2026-11-01T00:00"})
```

PC worker logs are on each PC (the worker writes `pilot.log` in its output folder); lines such as `SEATED`, `LEFT`, `REBUY`, `BUSTED`, `BREAK`, `SHOW` and `Task failed` describe what the bot did.

## 11. Typical deploy order

When a change touches several components, deploy in this order and verify each step before the next:

1. Migrations (§4), plus grants for any new table.
2. Scheduler function app (§5).
3. Backoffice (§6).
4. PDecision build (§8), if changed.
5. PC release and rollout (§7).

The PC release goes last because rolling out takes the longest and every PC must find the schema and APIs it expects. Code shipped earlier must tolerate the old PC worker still running until the rollout completes; for example, the worker reads new policy columns with a fallback default (`policy.get('Column')`).
