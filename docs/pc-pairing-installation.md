# Install PokerSuite with one EXE

New PC setup | Setup 1.0.5 / Agent 1.0.8 | 29 October 2026

## 1. Prepare Windows

Use Windows x64, including Windows 10, and the Windows account that will run the bots. Setup itself is self-contained. PDecision and PokerController still require Windows prerequisites: .NET 8 base Runtime x64, .NET 8 Desktop Runtime x64, ASP.NET Core 8 Runtime x64, SQL Server Express LocalDB x64 and SQL Server ODBC Driver 17 or 18 x64. Setup checks that all three .NET frameworks meet the bundled minimum patch version (currently 8.0.33), not just that an older 8.0 folder exists. Setup checks for these before issuing a pairing code. Click Install missing components: the official Microsoft installers are bundled inside Setup. Confirm the Microsoft license terms and approve any Windows administrator prompts. After verification completes, click Get pairing code. If an installer requires a restart, restart Windows and rerun Setup; remaining components are detected automatically.

[.NET 8 Desktop and ASP.NET Core runtimes](https://dotnet.microsoft.com/en-us/download/dotnet/8.0)

[SQL Server Express LocalDB](https://learn.microsoft.com/en-us/sql/database-engine/configure-windows/sql-server-express-localdb)

[SQL Server ODBC driver](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)

## 2. Run PokerSuite.Setup.exe

Download PokerSuite Setup.exe from Backoffice > Updates > Set up a new PC, or copy that EXE from your administrator. Run it on the new PC. You do not need Git, Python, the old installer ZIP or any JSON files. The EXE is not currently Authenticode signed; Windows may show a publisher warning.

Setup displays the PC name and physical adapter MAC addresses. Click Get pairing code. Give the displayed code to the main administrator and keep setup open. The code expires after 30 minutes. Setup resumes an unexpired request when reopened under the same Windows account. Once enrollment exists, it hides pairing controls and opens the status screen automatically, even if the old pairing-request file is still present. Setup and agent versions are always visible. If local enrollment files are missing but the original device key is still available, setup verifies the prior approval and shows Restore approved installation instead of asking for another pairing code.

# Approve the PC in Backoffice

## 3. Main administrator approval

Sign in to Backoffice with the designated main administrator account. Select the intended customer and site, then open Updates. In Set up a new PC, enter the code shown on that PC and click Find PC.

Confirm the PC name and adapter MAC match the intended machine. Select its adapter, entry capacity and initial release. Click Approve and install. Only explicitly designated main administrators can approve a PC; ordinary customer operators cannot register devices through this flow.

Approval registers a new MAC for the selected customer/site or uses an existing registration for that customer. A MAC belonging to a different customer, a managed installation already in use, or an existing pending installation cannot be silently reassigned. For the already registered Evenbet PC 2, select MAC 02-90-1D-03-85-65; it retains machine ID 6.

## 4. Let setup finish

The approved setup receives its machine token and runtime settings through HTTPS in a package encrypted for that PC private key. It saves them with Windows user-bound encryption, installs the updater and registers its logon task. The selected initial release is already queued: no separate update scheduling or file copying is needed.

The agent downloads and verifies PDecision and the packaged PokerController. It starts PDecision first, waits for a ready health response, then starts PokerController and checks its version and heartbeat. First startup may take longer while resources synchronize and local statistics databases are created.

Follow progress on Updates. Existing customer rollouts still serialize installations: a paused rollout or an earlier PC recovering traffic can delay a newly queued installation. Do not bypass that ordering by starting duplicate application copies.

[Backoffice Updates](https://lively-rock-032158003.4.azurestaticapps.net/#updates)

# Startup, recovery and help

## Automatic startup and restart

The agent starts when the enrolled Windows user logs on. It starts the managed PDecision and PokerController in order and restarts applications that exit, including during traffic recovery. Stay signed in; this is an interactive logon task, not a service that starts before login. Locking the desktop preserves the session; signing out ends it.

The last approved supervision mode survives a temporary backoffice outage. An installation or rollback journal prevents normal restarts from racing an intentional shutdown. Applications that remain alive but unhealthy are reported unhealthy; the agent does not force-kill them automatically.

## Where to check

The Setup and Status window shows the authenticated machine ID, updater connection/heartbeat, runtime readiness, application versions, health and current installation task. Its bottom status bar stays visible and refreshes automatically. Opening it can start a stopped installed agent when runtimes are ready. No new pairing is offered for an existing enrollment. Backoffice Updates shows the agent heartbeat, installed release, health and task progress. Machines shows the reported application versions and online state. A task may remain in traffic recovery while entries return gradually after successful application startup.

Agent log: C:\PokerSuite\Managed\updater.log. Current application paths and worker run folder: C:\PokerSuite\Managed\active.json. PDecision logs: C:\PokerSuite\Logs. The active worker run folder contains status.json and worker.log.

## If setup cannot finish

Missing prerequisites or an older .NET patch: click Install missing components to use the bundled Microsoft installers. The same button repairs an already-enrolled PC without replacing its enrollment. If an initial installation failed, close its application error dialog, cancel the failed rollout and schedule the same release again after runtime repair. Already installed components are skipped. Setup verifies installer checksums and Microsoft signatures before starting them. Folder or scheduled-task permissions: use the intended Windows account and ask the Windows administrator to grant access to C:\PokerSuite or perform the required installation under that account. Windows encryption is tied to the user; do not enroll under a different administrator account and then switch users.

Expired code: request a new code. If an installation was already approved or queued, the administrator should review that existing task before approving another request. Do not overwrite an existing managed installation with fresh setup. Use its existing updater and Backoffice Updates instead.

## Administrator credential provisioning

The site runtime profile is configured once by the main administrator using tools/configure_pairing.py. It is encrypted in the database using an API-side key, never displayed in the browser, and delivered only in a device-encrypted approval envelope. Changing the Windows account or reinstalling Windows can make local protected files unreadable. Use the original Windows account. When the original device key remains available, Restore approved installation restores the missing agent files and encrypted settings without new pairing. Recovery requires the updater to be offline, no open sessions and no active update; it can safely requeue the same approved release after a failed initial installation. If the key is lost or administrator approval was revoked, administrator recovery is required. Never copy another PC enrollment.

The former JSON-based installer remains available for existing deployments, but is no longer needed for this pairing workflow.
