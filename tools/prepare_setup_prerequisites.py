"""Download official Microsoft packages, verify signatures, build embedded manifest."""
import hashlib,json,subprocess,sys
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT.parent/'PokerController/artifacts/prerequisites/payload';OUT.mkdir(parents=True,exist_ok=True)
r=requests.get('https://dotnetcli.blob.core.windows.net/dotnet/release-metadata/8.0/releases.json',timeout=30);r.raise_for_status();release=r.json()['releases'][0]
packages=[]
for section,pid,label in [('runtime','runtime','.NET 8 Runtime x64'),('windowsdesktop','desktop','.NET 8 Desktop Runtime x64'),('aspnetcore-runtime','aspnet','ASP.NET Core 8 Runtime x64')]:
 f=next(f for f in release[section]['files'] if f['rid']=='win-x64' and f['name'].endswith('.exe'))
 packages.append(dict(id=pid,label=label,file=pid+'.exe',url=f['url'],minimumVersion=release['release-version'],officialSha512=f['hash'],kind='exe',args=['/install','/passive','/norestart']))
packages.extend([
 dict(id='vc',label='Microsoft Visual C++ Runtime x64',file='vc.exe',url='https://aka.ms/vs/17/release/vc_redist.x64.exe',kind='exe',args=['/install','/passive','/norestart']),
 dict(id='odbc',label='SQL Server ODBC Driver 17 or 18 x64',file='odbc.msi',url='https://go.microsoft.com/fwlink/?linkid=2378279',kind='msi',args=['IACCEPTMSODBCSQLLICENSETERMS=YES']),
 dict(id='localdb',label='SQL Server Express LocalDB x64',file='localdb.msi',url='',kind='msi',args=['IACCEPTSQLLOCALDBLICENSETERMS=YES'])])
for package in packages:
 path=OUT/package['file']
 if package['id']=='localdb':
  sources=list((OUT.parent/'localdb-media').rglob('SqlLocalDB.msi'))
  if len(sources)!=1:raise SystemExit('Download official LocalDB media first using SQL2022-SSEI-Expr.exe /ACTION=Download /MEDIATYPE=LocalDB')
  import shutil;shutil.copy2(sources[0],path);package['url']='Official SQL Server 2022 Express LocalDB download media'
 elif not path.exists():
  with requests.get(package['url'],stream=True,timeout=120) as response:
   response.raise_for_status()
   if not response.url.startswith(('https://builds.dotnet.microsoft.com/','https://download.microsoft.com/','https://download.visualstudio.microsoft.com/')):raise RuntimeError('Unexpected Microsoft download host')
   with path.open('wb') as f:
    for block in response.iter_content(1024*1024):f.write(block)
 if package.get('officialSha512') and hashlib.sha512(path.read_bytes()).hexdigest()!=package['officialSha512']:raise RuntimeError('Official Microsoft checksum mismatch')
 script=OUT.parent/'verify-signature.ps1'
 script.write_text("$s=Get-AuthenticodeSignature -LiteralPath '"+str(path).replace("'","''")+"';if($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch '(^|,\s*)O=Microsoft Corporation(,|$)'){throw 'Microsoft installer signature invalid'}")
 subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script)],check=True,capture_output=True)
 package['size']=path.stat().st_size;package['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
 print('Verified Microsoft package:',package['id'],round(package['size']/1024/1024,1),'MB',flush=True)
(OUT/'manifest.json').write_text(json.dumps(packages,indent=2))
print('Prepared bundled prerequisite manifest.')
