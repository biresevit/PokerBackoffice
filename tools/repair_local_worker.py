"""Controlled local worker-only repair; keep the identical PDecision running."""
import argparse,base64,ctypes,hashlib,json,os,subprocess,sys,time,uuid,zipfile
from ctypes import wintypes as w
from datetime import datetime,timezone
from pathlib import Path
from cryptography.hazmat.primitives import serialization,hashes
from cryptography.hazmat.primitives.asymmetric import padding
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'api'));sys.path.append(str(ROOT.parent/'PokerController/.venv/Lib/site-packages'))
import psutil,requests
from backoffice.db import session
from backoffice.store import Store,Context
p=argparse.ArgumentParser();p.add_argument('--label',required=True);p.add_argument('--apply',action='store_true');args=p.parse_args()
managed=Path(r'C:\PokerSuite\Managed');agent=Path(r'C:\PokerSuite\Updater');config=agent/'agent.json'
cfg=json.loads(config.read_text(encoding='utf-8-sig'));active_path=managed/'active.json';previous=json.loads(active_path.read_text(encoding='utf-8-sig'))
if cfg['MachineId']!=1 or cfg['SiteId']!=1 or Path(cfg['Root'])!=managed:raise SystemExit('This maintenance procedure is scoped to the local MSI worker')
with session() as db:
 if db.one('SELECT TaskId FROM scheduler.MachineUpdateTask WHERE MachineId=1 AND StartedUtc IS NOT NULL AND CompletedUtc IS NULL'):raise SystemExit('An application rollout is active')
 release=db.one('SELECT * FROM scheduler.UpdateRelease WHERE Label=%s AND Enabled=1',args.label)
if not release:raise SystemExit('Signed release not found')
manifest=json.loads(release['ManifestJson']);trusted=False
for pem in cfg['TrustedKeys']:
 try:serialization.load_pem_public_key(pem.encode()).verify(base64.b64decode(release['Signature']),release['ManifestJson'].encode(),padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=32),hashes.SHA256());trusted=True
 except Exception:pass
if not trusted:raise SystemExit('Release signature rejected')
package=ROOT/'artifacts/releases'/(args.label+'.zip')
if package.stat().st_size!=manifest['size'] or hashlib.sha256(package.read_bytes()).hexdigest()!=manifest['sha256']:raise SystemExit('Package checksum rejected')
version=managed/'versions'/str(release['ReleaseId'])
if not version.exists():
 version.mkdir()
 with zipfile.ZipFile(package) as z:
  for entry in z.infolist():
   dest=(version/entry.filename).resolve()
   if not dest.is_relative_to(version.resolve()) or ':' in entry.filename or ((entry.external_attr>>16)&0xf000)==0xa000:raise SystemExit('Invalid package path')
  z.extractall(version)
 (version/'.package-sha256').write_text(manifest['sha256'])
old_decision=Path(previous['decisionCwd'])
for file in (version/'pdecision').rglob('*'):
 if file.is_file() and (not (old_decision/file.relative_to(version/'pdecision')).is_file() or hashlib.sha256(file.read_bytes()).digest()!=hashlib.sha256((old_decision/file.relative_to(version/'pdecision')).read_bytes()).digest()):raise SystemExit('PDecision differs; a worker-only repair cannot be used')
if (managed/'operation.json').exists():raise SystemExit('A local application switch is active')
print('Verified signed release and identical PDecision application files.',flush=True)
if not args.apply:raise SystemExit(0)
k=ctypes.windll.kernel32;k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE;k.CloseHandle.argtypes=[w.HANDLE];k.GetProcessTimes.argtypes=[w.HANDLE,ctypes.POINTER(w.FILETIME),ctypes.POINTER(w.FILETIME),ctypes.POINTER(w.FILETIME),ctypes.POINTER(w.FILETIME)]
def ticks(pid):
 handle=k.OpenProcess(0x1000,False,pid)
 if not handle:raise RuntimeError('Cannot read process identity')
 try:
  values=[w.FILETIME() for _ in range(4)]
  if not k.GetProcessTimes(handle,*[ctypes.byref(x) for x in values]):raise RuntimeError('Cannot read process times')
  return (values[0].dwHighDateTime<<32)+values[0].dwLowDateTime+504911232000000000
 finally:k.CloseHandle(handle)
def save(value):
 tmp=active_path.with_suffix('.repair.tmp');tmp.write_text(json.dumps(value,indent=2));os.replace(tmp,active_path)
try:worker=psutil.Process(previous['workerPid'])
except psutil.NoSuchProcess:worker=None
if worker and (Path(worker.exe())!=Path(previous.get('workerProcessExe') or previous['workerExe']) or ticks(worker.pid)!=previous['workerStarted']):raise SystemExit('Old worker process identity changed')
agent_processes=[q for q in psutil.process_iter(['exe']) if (q.info['exe'] or '').lower()==str(agent/'PokerSuite.Updater.exe').lower()]
for process in agent_processes:process.terminate();process.wait(10)
try:
 print('Requesting graceful worker stop; PDecision remains running.',flush=True)
 (Path(previous['workerOutput'])/'stop').write_text('Controlled worker repair; preserve server seats for restart reconciliation.')
 if worker:worker.wait(180)
 output=managed/'runs'/('presence-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'));output.mkdir()
 environment=os.environ.copy();runtime=json.loads((managed/'config/worker-env.json').read_text(encoding='utf-8-sig'))
 for key,value in runtime.items():
  if key not in ('SCHEDULE_SQL_CONNECTION_STRING','SqlConnectionString','SCHEDULE_ODBC_DRIVER'):raise RuntimeError('Unsupported worker setting')
  environment[key]=value
 target=dict(previous);exe=version/'controller/PokerController.exe';argv=['--site-id','1','--machine-id','1','--output',str(output)]
 launcher=(output/'launcher.log').open('w')
 child=subprocess.Popen([str(exe),*argv],cwd=exe.parent,env=environment,stdout=launcher,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
 target.update(releaseId=str(release['ReleaseId']),workerExe=str(exe),workerProcessExe=str(exe),workerCwd=str(exe.parent),workerArgs=argv,workerPid=child.pid,workerStarted=ticks(child.pid),workerOutput=str(output));save(target)
 deadline=time.monotonic()+900;next_notice=0
 while time.monotonic()<deadline:
  if child.poll() is not None:raise RuntimeError('Repaired worker exited; inspect '+str(output/'worker.log'))
  status=output/'status.json'
  if status.exists():
   try:
    payload=json.loads(status.read_text())
    with session() as db:state=db.one('SELECT IsReady,WorkerEpoch FROM scheduler.MachineAssignment WHERE MachineId=1 AND SiteId=1')
    if payload.get('controller_version')==manifest['controllerVersion'] and state['IsReady'] and str(state['WorkerEpoch'])==payload['epoch']:break
   except (ValueError,OSError):pass
  if time.monotonic()>=next_notice:print('Waiting for startup seat reconciliation...',flush=True);next_notice=time.monotonic()+30
  time.sleep(2)
 else:raise RuntimeError('Worker reconciliation timed out; inspect '+str(output/'worker.log'))
 health=requests.get(cfg['DecisionHealthUrl'],timeout=5).json()
 if health.get('status')!='ready' or health.get('version')!=manifest['pdecisionVersion']:raise RuntimeError('PDecision health verification failed')
 with session() as db:
  db.execute('UPDATE scheduler.MachineUpdateAgent SET CurrentReleaseId=%s WHERE MachineId=1',release['ReleaseId'])
  Store(db,Context(14004,'local','worker-maintenance','operator')).audit('worker.repair',1,{'release':args.label,'mode':'restart reconciliation','pdecision_reused_identical_files':True})
 print('Worker repaired and heartbeat verified:',payload.get('entries'),flush=True)
finally:
 if agent_processes:subprocess.Popen([str(agent/'PokerSuite.Updater.exe'),'--config',str(config)],cwd=agent,creationflags=subprocess.CREATE_NO_WINDOW)
