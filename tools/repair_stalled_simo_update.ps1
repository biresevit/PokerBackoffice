# Run on the affected VM as the Windows user who installed PokerSuite.
# Archives only the reviewed, failed local update journal. Apps and enrollment are preserved.
$ErrorActionPreference = 'Stop'
$expected = @{
    'VMI3743337' = @{ MachineId = 1024; FailedTask = '7d090dde-cf42-4042-8e16-e488d87d3b0c' }
    'VMI3743338' = @{ MachineId = 1026; FailedTask = 'b3e55736-b124-419f-9e3b-0f6d9db3eb27' }
}
$target = $expected[$env:COMPUTERNAME]
if (-not $target) { throw 'This repair is only for VMI3743337 and VMI3743338.' }
$root = 'C:\PokerSuite\Managed'
$operationPath = Join-Path $root 'operation.json'
if (-not (Test-Path -LiteralPath $operationPath)) {
    Write-Output 'No failed local update journal remains. Ask the administrator to resume the corrected rollout.'
    exit 0
}
Add-Type -AssemblyName System.Security
$protectedConfig = 'C:\PokerSuite\Updater\agent.protected'
if (Test-Path -LiteralPath $protectedConfig) {
    $raw = [Security.Cryptography.ProtectedData]::Unprotect(
        [IO.File]::ReadAllBytes($protectedConfig), $null,
        [Security.Cryptography.DataProtectionScope]::CurrentUser)
    $cfg = [Text.Encoding]::UTF8.GetString($raw) | ConvertFrom-Json
} else {
    $cfg = Get-Content -LiteralPath 'C:\PokerSuite\Updater\agent.json' -Raw | ConvertFrom-Json
}
if ($cfg.MachineId -ne $target.MachineId -or $cfg.SiteId -ne 1006 -or $cfg.Root -ne $root) {
    throw 'The enrollment does not match this reviewed Simo machine.'
}
$uri = $cfg.BaseUrl.TrimEnd('/') + '/api/updater/' + $cfg.MachineId + '/status'
$status = Invoke-RestMethod -Method Post -Uri $uri -ContentType 'application/json' -Body '{}' -Headers @{ 'X-Updater-Token' = $cfg.Token }
if (-not $status.authenticated -or $status.machine_id -ne $target.MachineId -or
    $status.update.status -ne 'stopping' -or $status.update.rollout_status -ne 'paused' -or
    $status.apps_healthy -or $status.worker_ready) {
    throw 'Server state changed. Repair stopped; ask the administrator to review the machine.'
}
$operation = Get-Content -LiteralPath $operationPath -Raw | ConvertFrom-Json
if ($operation.Phase -ne 'failed' -or $operation.TaskId -ne $target.FailedTask) {
    throw 'The local journal is not the reviewed failed attempt. No files were changed.'
}
$backup = Join-Path $root ('operation.failed-backup-' + [DateTime]::UtcNow.ToString('yyyyMMddHHmmss') + '.json')
Move-Item -LiteralPath $operationPath -Destination $backup
Write-Output 'Archived the reviewed failed update journal. Enrollment and application files were preserved.'
Write-Output 'Now resume the corrected rollout in Backoffice Updates. No new pairing is required.'
