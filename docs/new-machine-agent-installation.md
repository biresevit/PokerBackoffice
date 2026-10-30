# New machine installation

PokerSuite agent 1.0.7 | Windows x64 | 29 October 2026

## What the agent installs

A new PC does not need a source checkout, Git or Python. Install Windows prerequisites, register and enroll the PC, and provide its protected runtime settings. After you schedule its first installation on the backoffice Updates page, the agent downloads the signed release containing PDecision and the PyInstaller-packaged PokerController, then starts both applications.

Installing the agent alone does not choose a release or authorize a PC. An operator selects the release and schedules the installation from the website. Application credentials are provisioned separately from the updater token.

## Before starting

1. Use a Windows x64 PC and the Windows account that will run the applications. Keep that account signed in during operation. The agent starts at user logon; it is not a service that starts before anyone signs in.

2. Install the x64 .NET 8 Desktop Runtime AND ASP.NET Core Runtime. PDecision needs both frameworks; the Desktop Runtime also supplies the base .NET runtime.

3. Install SQL Server Express LocalDB for local player-statistics databases. Install SQL Server ODBC Driver 17, or Driver 18 with SCHEDULE_ODBC_DRIVER set accordingly in the worker settings.

4. Allow the network connections required by the existing PokerSuite setup: backoffice and Azure Blob HTTPS, Azure SQL, the poker platform and solver/resource services. Do not expose the local decision API to the Internet. Allow sufficient disk space for strategy resources, local databases and two release copies.

[Microsoft: .NET 8 runtime downloads](https://dotnet.microsoft.com/en-us/download/dotnet/8.0)

[Microsoft: SQL Server Express LocalDB](https://learn.microsoft.com/en-us/sql/database-engine/configure-windows/sql-server-express-localdb)

[Microsoft: SQL Server ODBC driver downloads](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)

# 1. Register and authenticate the PC

## Collect the actual adapter MAC address

On the new PC, open PowerShell and run this command. Send the active physical Ethernet or Wi-Fi adapter MAC address and the PC name to your administrator. Keep that adapter present; a copied enrollment for another PC will be rejected.

```
hostname
Get-NetAdapter -Physical | Select-Object Name, MacAddress, Status
```

## Administrator: create the machine registration

The current backoffice can configure and enroll registered machines; it does not create new machine registrations. An administrator must register the MAC in dbo.CustomerMachine for the correct active customer, casino and platform. The existing dbo.Machine_Upsert procedure in PDecision/sql/CustomerMachines.sql performs registration.

Also add the machine to scheduler.MachineAssignment for its site, with the intended MaxEntries and IsEnabled, and add backoffice.MachineMetadata and backoffice.MachineAllowedSite records. The site and machine must belong to the same customer. Use the new MachineId, not the ID of a different PC.

## Operator: enroll through the website

Sign in with an operator account. Open Updates for the correct customer/site and choose Enroll / replace updater for the new machine. Save the downloaded agent-machine-ID.json. Download and extract the updater installer ZIP from the same page. Use installer 1.0.7 or later for fresh installations.

[Open Backoffice Updates](https://lively-rock-032158003.4.azurestaticapps.net/#updates)

## Two independent authentication checks

Updater: the downloaded JSON contains a private machine-scoped API token and trusted release-signing public keys. The agent checks the enrolled MAC locally; the server checks the token and registered machine/site. The token does not grant a website login.

PDecision: its own restricted database login reads the active machine/customer registration by MAC. PokerController uses its provisioned worker SQL login and machine/site assignment. A legacy Authentication.txt is not required by the current PDecision build. Registration and runtime settings are still required.

Keep enrollment and runtime-settings files private. Do not share them between customers, commit them to source control or include them in release ZIPs. Re-enrollment replaces the updater token and invalidates the previous enrollment.

# 2. Install the agent on a fresh PC

## Obtain two settings files from the administrator

pdecision.json: the approved appsettings.json for this customer, including Database.ConnectionString and the local Api configuration. The default health address is http://127.0.0.1:5005/api/health; it must match DecisionHealthUrl in the enrollment JSON.

worker-env.json: an object containing SCHEDULE_SQL_CONNECTION_STRING (native ODBC) or SqlConnectionString (ADO.NET). SCHEDULE_ODBC_DRIVER is optional. Use the dedicated worker login, not an administrator login. These settings are needed after reboot because the scheduled task does not inherit a developer terminal's private environment.

Example structure only; the administrator supplies real restricted credentials:

```
{
  "SCHEDULE_SQL_CONNECTION_STRING": "<restricted ODBC connection>"
}
```

## Run the installer

Extract the ZIP to a local setup folder and place the enrollment and settings files beside Install-Updater.ps1. Open PowerShell in that folder as the intended Windows account. Replace 7 below with your actual machine ID. If C:\PokerSuite cannot be created, have the administrator grant this account access to that folder.

```
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\Install-Updater.ps1 `
  -ConfigPath .\agent-machine-7.json `
  -FreshInstall `
  -DecisionSettingsPath .\pdecision.json `
  -WorkerSettingsPath .\worker-env.json
```

The installer saves protected settings under C:\PokerSuite\Managed\config, installs the agent under C:\PokerSuite\Updater and creates the scheduled task PokerSuite Updater ID. It starts the agent immediately. You do not need to install PDecision or PokerController manually.

## Schedule the first application installation

Wait for the agent to appear connected on Updates. Select a published release and this machine, then schedule the update now or choose a later start time. A fresh machine has no sessions to drain. The task verifies the download, installs both executables, starts PDecision and waits for ready, then starts PokerController and checks its version and heartbeat. First startup can take time while PDecision synchronizes resources and creates databases.

After successful installation, scheduling resumes if the site and machine are enabled and the current schedule requires entries. Traffic follows normal gradual scheduling. Keep the private setup files in protected storage or remove their temporary copies after installation.

# 3. Startup and automatic recovery

## What happens at Windows logon

Windows Task Scheduler starts the agent when the enrolled user signs in. The agent launches the installed PDecision first, waits for its ready health response, then launches PokerController. A network connection is needed for the first installation and normal poker operation.

## What happens when an application exits

For an installed managed release, the agent checks the recorded process identity. If PDecision or PokerController is no longer running, it attempts a restart, in the same startup order. It also does this while an update is restoring traffic. Failed restart attempts are paced with a 90-second retry interval; PDecision readiness can take up to two hours and controller startup up to 5 minutes.

The last server-approved supervision mode is stored locally. After normal supervision has been enabled, it continues through a temporary backoffice outage. Intentional update shutdowns disable supervision, and an unfinished installation journal blocks ordinary restarts so they cannot race installation or rollback.

This is process-exit recovery. An application that stays alive but becomes unhealthy is reported unhealthy and prevents the rollout from advancing; the agent does not force-kill it. Similarly, it does not kill unrelated applications with the same name. Do not manually launch duplicate copies.

## Updates and failures

Existing machines finish one bot session at a time before update shutdown. Downloads are authenticated with the pinned RSA signing key and verified by SHA-256. A startup failure attempts rollback when a previous release exists. On a first installation there is no older release to restore; failure pauses the rollout for review instead.

The next machine waits for health and traffic recovery. Other machines keep their schedules. To intentionally keep applications stopped, disable the updater scheduled task and stop the updater first; stopping only an application allows the agent to restart it. Do not interrupt the agent during installation or rollback.

## Where files are stored

```
C:\PokerSuite\Updater\agent.json
C:\PokerSuite\Managed\config\pdecision.json
C:\PokerSuite\Managed\config\worker-env.json
C:\PokerSuite\Managed\versions\<release-id>
C:\PokerSuite\Managed\runs\<run-id>
C:\PokerSuite\Managed\updater.log
```

# 4. Verify and troubleshoot

## Installation acceptance checks

On Updates, confirm a recent agent heartbeat, the intended installed release and healthy applications. On Machines, confirm the machine is online and both application versions are reported. A successful task can remain in traffic recovery while entries increase gradually; that does not mean the application installation is still running.

```
Get-ScheduledTask -TaskName "PokerSuite Updater 7"
Get-Process PDecision,PokerController -ErrorAction SilentlyContinue
Invoke-RestMethod http://127.0.0.1:5005/api/health
Get-Content C:\PokerSuite\Managed\updater.log -Tail 20
```

Expected health: status ready and the selected PDecision version. The current worker's run folder is recorded in Managed\active.json. Its status.json contains the controller version and heartbeat; worker.log contains startup and command details. PDecision logs are under C:\PokerSuite\Logs.

## Common problems

Agent absent: check that the intended Windows user is logged in, the scheduled task exists, .NET is installed and the enrolled MAC is present. Check updater.log. HTTP 401 normally means the token is invalid or has been replaced; another active updater instance can cause HTTP 409.

PDecision not ready: check machine/customer activation and MAC registration, Database.ConnectionString, network access, LocalDB and resource initialization. The health response and PDecision log give the reason. Allow initial resource synchronization time.

Controller fails: check worker-env.json, ODBC driver selection, restricted SQL permissions and machine/site assignment. An ODBC Driver 18-only PC needs SCHEDULE_ODBC_DRIVER set to ODBC Driver 18 for SQL Server if the ADO.NET-style setting is used, or that driver named directly in the native ODBC connection string.

Fresh installation remains queued: confirm the agent is connected and the customer has no paused rollout blocking later work. A machine with open session or entry records is treated as an existing machine and cannot bypass draining by claiming to be a fresh installation.

## Enroll an existing installation instead

For a running legacy Python worker, omit -FreshInstall and provide -ControllerRoot. The installer records the running process identities and preserves the machine settings. For an already managed installation it preserves active.json. Stop only the updater before replacing its binaries, and only when no installation/rollback is active. Never use -FreshInstall over an existing managed installation.

Agent upgrades are separate from application releases. Install the newer updater ZIP on each PC under controlled conditions; scheduling a PDecision/PokerController release does not replace the updater itself.

# Administrator registration example

Use this template in Azure SQL pokerdb with an administrator account. It is for a new Nenad / Evenbet PC on site 1. Replace the MAC and hostname, verify the customer/site and entry capacity, and adjust the casino/platform for other deployments. This is not run by the agent. The same script is saved as register-new-machine.sql beside this PDF.

```
-- Administrator template. Replace MAC/hostname; review customer/site.
SET XACT_ABORT ON;
BEGIN TRANSACTION;
DECLARE @customer nvarchar(100)=N'Nenad', @site int=1;
DECLARE @mac varchar(17)='AA-BB-CC-DD-EE-FF'; -- REPLACE
DECLARE @host nvarchar(200)=N'NEW-PC'; -- REPLACE
DECLARE @cid int=(SELECT CustomerId FROM dbo.Customer
                 WHERE CustomerName=@customer AND IsActive=1);
IF @cid IS NULL OR NOT EXISTS(SELECT 1 FROM scheduler.Site
    WHERE SiteId=@site AND CustomerId=@cid)
    THROW 51120,'Customer/site mismatch',1;
IF @mac='AA-BB-CC-DD-EE-FF' OR @host=N'NEW-PC'
    THROW 51121,'Replace example MAC and hostname',1;
IF EXISTS(SELECT 1 FROM dbo.CustomerMachine WHERE MacAddress=@mac)
    THROW 51122,'Machine already registered; review existing record',1;
EXEC dbo.Machine_Upsert @CustomerName=@customer,@MacAddress=@mac,
    @Casino=N'Evenbet',@Platform=N'EvenBet',@Description=@host;
DECLARE @mid int=(SELECT MachineId FROM dbo.CustomerMachine
                 WHERE MacAddress=@mac AND CustomerId=@cid);
IF @mid IS NULL THROW 51123,'Machine registration failed',1;
INSERT scheduler.MachineAssignment
    (MachineId,SiteId,MaxEntries,IsEnabled)
    VALUES(@mid,@site,30,1);
INSERT backoffice.MachineMetadata(MachineId,HostName)
    VALUES(@mid,@host);
INSERT backoffice.MachineAllowedSite(MachineId,SiteId)
    VALUES(@mid,@site);
COMMIT;
SELECT @mid AS NewMachineId;

```

After registration, use the returned MachineId when enrolling on Updates. Provision the approved restricted PDecision and worker settings privately; registration does not generate database passwords. The operator can then follow pages 2-5 to enroll, install and verify the new PC.
