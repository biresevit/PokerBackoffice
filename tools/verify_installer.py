"""Exercise fresh installer in a temporary folder; no real apps/tasks/network."""
import json,shutil,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
folder=Path(tempfile.mkdtemp(prefix='PokerSuite-installer-test-'))
installer=folder/'Install-Updater.ps1'
shutil.copy2(ROOT.parent/'PokerController/updater/Install-Updater.ps1',installer)
(folder/'agent').mkdir();(folder/'agent/PokerSuite.Updater.exe').write_text('fake')
(folder/'enroll.json').write_text(json.dumps({'Token':'test-only','TrustedKeys':['test-only'],'MachineId':999999,'SiteId':1,'Root':str(folder/'Managed')}))
(folder/'decision.json').write_text(json.dumps({'Database':{'ConnectionString':'test-only'}}))
(folder/'worker.json').write_text(json.dumps({'SqlConnectionString':'test-only'}))
check=folder/'check.ps1'
check.write_text('''$ErrorActionPreference='Stop'
function Get-Process { param($Name,$Id,$ErrorAction) return $null }
function Get-CimInstance { param($ClassName) return @() }
function Start-Process { param($FilePath,$ArgumentList,$WorkingDirectory,$WindowStyle) if($WindowStyle -ne 'Hidden'){throw 'Agent must start hidden'}; $global:launched=$true }
& (Join-Path $PSScriptRoot 'Install-Updater.ps1') -ConfigPath (Join-Path $PSScriptRoot 'enroll.json') -FreshInstall -DecisionSettingsPath (Join-Path $PSScriptRoot 'decision.json') -WorkerSettingsPath (Join-Path $PSScriptRoot 'worker.json') -NoScheduledTask
$root=Join-Path $PSScriptRoot 'Managed'
if(Test-Path (Join-Path $root 'active.json')){throw 'Fresh installation must not invent running applications'}
foreach($file in @('config\\pdecision.json','config\\worker-env.json')){ $settings=Get-Content (Join-Path $root $file) -Raw | ConvertFrom-Json; if(-not $settings){throw 'Settings not readable'} }
if(-not $global:launched){throw 'Agent was not started'}
Write-Output 'Verified fresh installer, protected readable runtime settings and hidden agent launch.'
''')
subprocess.run(['powershell.exe','-NoProfile','-File',str(check)],check=True)
