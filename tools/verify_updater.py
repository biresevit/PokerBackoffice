"""Run the real agent against isolated fake apps/API; no live poker connections."""
import base64,json,os,shutil,socket,subprocess,sys,tempfile,threading,time,uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa,padding
ROOT=Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT.parent/'PokerController/.venv/Lib/site-packages'))
import psutil
APPS=ROOT.parent/'PokerController/artifacts/updater-smoke-apps'
AGENT=ROOT.parent/'PokerController/artifacts/updater-agent/PokerSuite.Updater.exe'


def port():
 with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]


def copy_app(target,name,decision='old',controller='old',fail=False):
 target.mkdir(parents=True,exist_ok=True)
 for source in APPS.iterdir():
  if source.is_file() and source.suffix!='.pdb':shutil.copy2(source,target/source.name)
 shutil.copy2(APPS/'FakeApplications.exe',target/name)
 (target/'build-info.json').write_text(json.dumps({'pdecisionVersion':decision,'controllerVersion':controller,'fail':fail}))


def wait_json(path,seconds=15):
 deadline=time.monotonic()+seconds
 while time.monotonic()<deadline:
  if path.exists():
   try:return json.loads(path.read_text(encoding='utf-8-sig'))
   except (OSError,ValueError):pass
  time.sleep(.1)
 raise TimeoutError(str(path))


def protect(source,target):
 script=source.parent/'protect-test.ps1'
 script.write_text("Add-Type -AssemblyName System.Security\n[IO.File]::WriteAllBytes('"+str(target)+"',[Security.Cryptography.ProtectedData]::Protect([IO.File]::ReadAllBytes('"+str(source)+"'),$null,[Security.Cryptography.DataProtectionScope]::CurrentUser))")
 subprocess.run(['powershell.exe','-NoProfile','-File',str(script)],check=True,capture_output=True)


def run(fail=False,fresh=False,protected=False,immediate=False):
 folder=Path(tempfile.mkdtemp(prefix='PokerSuite-updater-smoke-'))
 old=folder/'old';copy_app(old,'PDecision.exe');shutil.copy2(APPS/'FakeApplications.exe',old/'PokerController.exe')
 healthport=port();(old/'appsettings.json').write_text(json.dumps({'Port':healthport}))
 output=folder/'old-output';output.mkdir()
 old_decision=subprocess.Popen([str(old/'PDecision.exe')],creationflags=subprocess.CREATE_NO_WINDOW)
 old_worker=subprocess.Popen([str(old/'PokerController.exe'),'--output',str(output)],creationflags=subprocess.CREATE_NO_WINDOW)
 agent=None;server=None
 try:
  ds=wait_json(old/'PDecision.exe.started.json');ws=wait_json(old/'PokerController.exe.started.json')
  root=folder/'managed';(root/'config').mkdir(parents=True)
  (root/'config/pdecision.json').write_text(json.dumps({'Port':healthport,'Database':{'ConnectionString':'dummy-protected-decision'}}))
  if protected:
   protect(root/'config/pdecision.json',root/'config/pdecision.protected');(root/'config/pdecision.json').unlink()
   (root/'config/worker-env.json').write_text(json.dumps({'SqlConnectionString':'dummy-protected-worker'}))
   protect(root/'config/worker-env.json',root/'config/worker-env.protected');(root/'config/worker-env.json').unlink()
  active={'decisionExe':str(old/'PDecision.exe'),'decisionCwd':str(old),'decisionPid':ds['pid'],'decisionStarted':ds['started'],
          'workerExe':str(old/'PokerController.exe'),'workerCwd':str(old),'workerPid':ws['pid'],'workerStarted':ws['started'],
          'workerArgs':['--output',str(output)],'workerOutput':str(output)}
  if not fresh:(root/'active.json').write_text(json.dumps(active))
  else:
   old_worker.terminate();old_worker.wait(10);old_decision.terminate();old_decision.wait(10)
  rid=str(uuid.uuid4());tid=str(uuid.uuid4());version=root/'versions'/rid
  copy_app(version/'pdecision','PDecision.exe',decision='1.0.0.29',controller='new',fail=fail)
  copy_app(version/'controller','PokerController.exe',decision='1.0.0.29',controller='new')
  digest='0'*64;(version/'.package-sha256').write_text(digest)
  key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
  public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
  manifest=json.dumps({'format':1,'releaseId':rid,'pdecisionVersion':'1.0.0.29','controllerVersion':'new','sha256':digest,'size':1})
  signature=base64.b64encode(key.sign(manifest.encode(),padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=32),hashes.SHA256())).decode()
  task={'id':tid,'status':'preparing','paused':False,'release_id':rid,'manifest':manifest,'signature':signature,'url':'https://example.blob.core.windows.net/test.zip'}
  phases=[];done=threading.Event();result={}
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))) or b'{}')
    if self.path.endswith('/report'):
     phase=body['phase'];phases.append(phase)
     if phase=='staged':task['status']='stopping' if fresh else ('forcing' if immediate else 'reconciling')
     elif phase=='reconciled':task['status']='stopping'
     elif phase=='force_stopped':task['status']='stopping'
     elif phase in ('installing','verifying'):task['status']=phase
     elif phase in ('resuming','rolled_back','failed'):result['outcome']=phase;done.set()
     response={'accepted':True}
    else:response={'task':None if done.is_set() else task}
    data=json.dumps(response).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  installed=json.loads(Path(r'C:\PokerSuite\Updater\agent.json').read_text(encoding='utf-8-sig'))
  cfg={'BaseUrl':f'http://127.0.0.1:{server.server_port}','MachineId':999998 if fail else 999999,'SiteId':1,'Token':'test-'+str(uuid.uuid4()),'TrustedKeys':[public],
       'Root':str(root),'DecisionHealthUrl':f'http://127.0.0.1:{healthport}/api/health','ExpectedMac':installed['ExpectedMac']}
  config=folder/'agent.json';config.write_text(json.dumps(cfg))
  if protected:
   protect(config,folder/'agent.protected');config=folder/'agent.protected'
  agent=subprocess.Popen([str(AGENT),'--config',str(config)],creationflags=subprocess.CREATE_NO_WINDOW)
  assert done.wait(85),('Agent did not finish',phases,(root/'updater.log').read_text())
  time.sleep(.3)
  assert result['outcome']==('rolled_back' if fail else 'resuming'),(result,phases,(root/'updater.log').read_text())
  final=wait_json(root/'active.json')
  assert final.get('releaseId')==(None if fail else rid)
  expected=['staged','installing','verifying'] if fresh else ['staged','force_stopped','installing','verifying'] if immediate else ['staged','reconciling','reconciled','installing','verifying']
  assert expected==phases[:len(expected)],phases
  assert psutil.pid_exists(final['decisionPid']) and psutil.pid_exists(final['workerPid'])
  if protected:
   assert (version/'pdecision/appsettings.json').read_text()=='{}'
   assert wait_json(version/'pdecision/PDecision.exe.started.json')['protectedDecision']
   assert wait_json(version/'controller/PokerController.exe.started.json')['protectedWorker']
   print('Verified protected enrollment/settings and secret-free appsettings with injected runtime settings.')
  if fresh:
   previous_pid=final['workerPid'];psutil.Process(previous_pid).terminate()
   deadline=time.monotonic()+110
   while time.monotonic()<deadline:
    recovered=wait_json(root/'active.json')
    if recovered['workerPid']!=previous_pid and psutil.pid_exists(recovered['workerPid']):break
    time.sleep(.5)
   else:raise AssertionError('Worker was not automatically restarted')
   print('Verified fresh installation and automatic worker restart.')
  if fail:print('Verified automatic rollback and healthy old apps.')
  elif immediate:print('Verified immediate update: force-stopped apps regardless of graceful shutdown, then process replacement and healthy new apps.')
  else:print('Verified staged release, reconciled stop, process replacement and healthy new apps.')
 finally:
  if agent and agent.poll() is None:agent.terminate();agent.wait(10)
  for process in psutil.process_iter(['pid','exe']):
   exe=process.info['exe'] or ''
   if exe.lower().startswith(str(folder).lower()+os.sep):
    try:process.terminate();process.wait(5)
    except (psutil.NoSuchProcess,psutil.TimeoutExpired):pass
  if server:server.shutdown()

if __name__=='__main__':run();run(True);run(fresh=True,protected=True);run(immediate=True)
