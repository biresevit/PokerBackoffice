param([ValidateSet('live','recorded')][string]$Mode='live', [int]$CustomerId=14004, [int]$Port=4280, [int[]]$AdditionalCustomerIds=@())
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$pythonPath=Join-Path $projectRoot 'diagnostics/.venv/Scripts/python.exe'
if(!(Test-Path -LiteralPath $pythonPath)){throw 'Create diagnostics/.venv and install diagnostics/requirements.txt first; see docs/diagnostics.md.'}
if(!$env:OPENAI_API_KEY){$env:OPENAI_API_KEY=[Environment]::GetEnvironmentVariable('OPENAI_API_KEY','User')}
if($Mode -eq 'live' -and !$env:OPENAI_API_KEY){throw 'Configure OPENAI_API_KEY locally or pass -Mode recorded. Never paste API keys into chat.'}
$env:POKERFILL_DIAGNOSTICS_HISTORY=Join-Path $projectRoot 'artifacts/diagnostics/history.sqlite3'
$env:POKERFILL_DIAGNOSTICS_MODE=$Mode
$env:POKERFILL_DIAGNOSTICS_COLLECT_LOGS=if($Mode -eq 'live'){'1'}else{'0'}
$env:POKERFILL_DIAGNOSTICS_URL='http://127.0.0.1:4310'
$randomBytes=New-Object byte[] 48
$rng=[System.Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($randomBytes)
$rng.Dispose()
$env:POKERFILL_DIAGNOSTICS_TOKEN=[Convert]::ToBase64String($randomBytes)
$logRoot=Join-Path $projectRoot 'artifacts/diagnostics'
New-Item -ItemType Directory -Force $logRoot | Out-Null
$worker=Start-Process -FilePath $pythonPath -ArgumentList '-m','uvicorn','diagnostics.service:app','--host','127.0.0.1','--port','4310','--no-access-log' -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot 'worker.out.log') -RedirectStandardError (Join-Path $logRoot 'worker.err.log') -PassThru
$extraPreviews=@()
try {
    $extraPort=$Port
    foreach($extraCustomer in $AdditionalCustomerIds){
        $extraPort++
        $extraPreviews+=Start-Process -FilePath $pythonPath -ArgumentList 'tools/preview.py','--port',"$extraPort",'--customer-id',"$extraCustomer" -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
        Write-Host "Customer $extraCustomer diagnosis: http://127.0.0.1:$extraPort/backoffice#diagnostics"
    }
    Write-Host "AI diagnosis: http://127.0.0.1:$Port/backoffice#diagnostics ($Mode mode). Ctrl+C stops the preview."
    & $pythonPath (Join-Path $PSScriptRoot 'preview.py') --port $Port --customer-id $CustomerId
} finally {
    foreach($preview in $extraPreviews){if(!$preview.HasExited){Stop-Process -Id $preview.Id}}
    if(!$worker.HasExited){Stop-Process -Id $worker.Id}
    Remove-Item Env:POKERFILL_DIAGNOSTICS_TOKEN -ErrorAction SilentlyContinue
}
