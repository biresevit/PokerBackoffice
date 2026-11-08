# Rolling PC updates

Operators order updates from the **Updates** page. Select a signed release, select PCs in the required order, choose **Wait for sessions to finish** or **Update immediately**, and optionally choose a start time in the site timezone. Update tasks also appear in **Tasks ? Update PC**.

The scheduler serializes updates across the whole customer, including multiple sites. It downloads and verifies a release before pausing new joins. Other PCs continue their normal schedules throughout.

## Wait for sessions to finish (default, recommended)

On the selected PC the scheduler finishes one account session at a time using normal randomized leave pacing and waits for hand completion (`MachineUpdateTask.Status='draining'`). Nothing is cut off; a bot leaves a table the same way it would at the natural end of its session. This is the only mode that existed before immediate updates were added, and remains the default and the recommended choice.

## Update immediately

Choosing **Update immediately** sets `UpdateRollout.Immediate=1` for the whole rollout. As soon as the release is staged on a PC, its task skips `draining` entirely and goes straight to `forcing`: the updater agent kills PDecision and PokerController outright (no cooperative "stop" sentinel, no graceful window-close, no wait for the current hand), regardless of any open table entries or account sessions.

This is faster, but it is a real interruption, not a natural session end:
- Hands in progress are abandoned mid-hand from the bot's side ? to the poker platform this looks like a crashed or disconnected client, not a player leaving normally.
- Any entries/sessions still open at the moment of the kill are recorded as cut off (`scheduler.AccountSession.EndReason='forced_update'`, `scheduler.Command.ResultCode='forced_update'`), **not** as confirmed absent from the table. This is different from the existing crash-recovery reconciliation (`EndReason='software_update'` / `ResultCode='reconciled_absent'`), which only closes entries after a fresh seat snapshot proves the bot actually left ? an immediate update does not wait for or require that proof.
- The backoffice UI asks for confirmation before submitting an immediate rollout, and marks it with a red **Immediate** badge on the rollout card so it's clearly distinguishable from a normal rollout in the history list.

Use it only when the delay of a normal rollout is unacceptable and the account-safety/detection tradeoff above has been accepted for that PC's sessions.

After the applications stop (gracefully via `draining`?`stopping`, or via `forcing`?`stopping` for an immediate update), the updater switches to an extracted version folder, starts PDecision, checks `/api/health` and its version, then starts PokerController and verifies its startup version and heartbeat. Scheduling resumes only after those checks. The next PC waits for a 60-second health period and at least 80% of the original entry count still needed by the current schedule. Reduced schedules lower that recovery requirement.

A failed update pauses the rollout. Startup failures attempt automatic rollback to the previous application pair. A rollback that cannot be verified leaves the PC in maintenance for manual review. Pausing during downloading/draining/forcing blocks further update departures; an active installation must finish or roll back before it can be paused. Cancelling remaining work does not interrupt an installation or undo leave commands already issued.

## One-time PC enrollment

New PCs use [PokerSuite Setup and pairing](pc-pairing-installation.pdf). Download the single EXE from Updates, run it on the PC, and approve its pairing code using the designated main administrator account. Approval registers or reuses the customer/site machine, delivers its encrypted runtime profile and queues its first release. JSON files are no longer copied manually. Setup 1.0.3 bundles the official Microsoft prerequisite installers. Its Install missing components button verifies signatures and checksums, installs only missing components with Windows administrator approval, and rechecks before pairing. Installer-requested restarts are left to the user; setup resumes detection after restart.

Site runtime profiles are encrypted in `backoffice.SetupProfile` with an API-side `BACKOFFICE_PAIRING_KEY`. Configure them and explicit main-administrator membership with `tools/configure_pairing.py`. Approval is scoped to the selected customer/site. Public requests are rate limited and expire in 30 minutes; polling/acknowledgement requires a signed device-key proof. Credentials are encrypted for that RSA device key and removed from the pairing record after acknowledgement. The updater reads Windows user-bound DPAPI files, injects PDecision settings into its environment and avoids plaintext credential appsettings in managed releases.

Existing JSON-based installations remain supported. Their ordinary rolling updates do not require re-pairing. Agent upgrades remain separate from application releases; setup contains agent 1.0.8.

## Release publishing

Build PokerController on Windows with the local worker modules included:

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --onedir --name PokerController --distpath artifacts\fleet-package --workpath artifacts\fleet-build --specpath artifacts --paths ..\ScheduleController --collect-submodules poker_controller --collect-submodules schedule_controller updater\worker_entry.py
dotnet publish updater\PokerSuite.Updater.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -o artifacts\updater-agent
```

Publish from PokerBackoffice with its development venv and the existing administrator environment:

```powershell
.\.venv\Scripts\python.exe tools\publish_release.py --label 2026.10.29.3 --controller-version 0.1.0+365faaa.updater2
```

The publisher uses the already validated obfuscated PDecision deliverable, excludes machine settings/debug mappings, packages both applications, and uploads private Azure blobs. An RSA-PSS signature authenticates the exact manifest and SHA-256 authenticates the ZIP. The publisher private key stays under `%LOCALAPPDATA%\PokerSuitePublisher`, outside Git and customer packages. Back it up securely; existing agents trust its public key.

Use `tools/publish_updater.py --version VERSION` to publish a newer initial installer separately without changing an immutable application release. Existing agents require a controlled agent upgrade; application rollouts update PDecision/PokerController, not the agent itself. Download URLs are read-only SAS URLs with a one-year expiry and must be renewed before expiry.

## Verification

Database migration tests roll back all changes. The real agent also has a signature/API-contract/path self-test (`--self-test`). `tools/verify_updater.py` runs isolated fake applications and a local API to test actual process replacement, a stopped-worker reconciliation phase, health checks, and automatic rollback without contacting poker services. It does not yet exercise the `forcing` (immediate update) path; that should be added before relying on it as a regression check for immediate updates.

Unconfirmed table entries never count as proof of a drained PC. The scheduler first drains confirmed sessions. Only complete fresh seat snapshots from that worker epoch can prove the remaining entries absent. The agent then stops the already-drained worker, and the API closes that absent journal after confirming the worker stopped. Present or stale unconfirmed seats keep the update blocked for reconciliation. An immediate update deliberately skips this proof-of-absence step (see "Update immediately" above); it closes whatever is still open right after the forced stop instead of waiting to confirm it.

## Live validation (2026-10-29)

Release `2026.10.29.3` was installed on MSI using updater `1.0.6`. The original worker drained its sessions, fresh complete seat snapshots proved its remaining unconfirmed entries absent, and the stopped-worker reconciliation closed that journal. PDecision restarted from the managed release folder and reported `ready`, version `1.0.0.29`. The packaged PokerController reported `0.1.0+365faaa.updater2`; the control plane accepted the release and reopened scheduling. Traffic recovery continues at normal pacing. Isolated process tests also verified automatic rollback to the previous pair after a startup failure.

## Building Setup with bundled prerequisites

Use tools/prepare_setup_prerequisites.py after downloading the official SQL Server 2022 LocalDB media. The tool downloads official .NET 8 Desktop/ASP.NET, Visual C++ and ODBC x64 installers, validates Microsoft Authenticode signatures, verifies the .NET release SHA-512 checksums, and creates a SHA-256 resource manifest under PokerController/artifacts/prerequisites/payload. Setup 1.0.3 includes the base .NET runtime explicitly and checks minimum patch versions for Microsoft.NETCore.App, Microsoft.WindowsDesktop.App and Microsoft.AspNetCore.App. Older 8.0 directories and incomplete framework folders no longer satisfy detection. Runtime repair on an enrolled PC preserves its enrollment. Publish updater/setup/PokerSuite.Setup.csproj as self-contained win-x64, single file. The --prerequisite-self-test switch extracts all embedded packages and validates their signatures and checksums without installing software.

## Setup status and missing-file recovery (1.0.5)

Setup always displays its own version, bundled/installed agent versions, authentication state and current action. Valid enrollment opens monitoring immediately. If enrollment files are missing, the original Windows-user DPAPI device key and saved request can prove the completed approval even after the short pairing code expires. Completed approval records retain the public device key until administrator revocation/replacement. A signed restore request may rotate the machine token and return a device-encrypted runtime package only when the agent is offline, no sessions/entries are open, and no update is active. A failed first installation may be requeued for its exact previously approved enabled release; other unfinished rollout work is never cancelled automatically. Restoration reinstalls all agent support files and preserves application state. No MAC-only credential recovery is permitted.
