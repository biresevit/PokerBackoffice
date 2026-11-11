"""Local mock API checks idle updater cadence and single diagnostic collector ownership."""
import json
import shutil
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
AGENT=ROOT.parent/'PokerController/artifacts/updater-agent/PokerSuite.Updater.exe'
folder=Path(tempfile.mkdtemp(prefix='PokerSuite-poll-smoke-')).resolve()
assert folder.parent==Path(tempfile.gettempdir()).resolve()
hits={'poll':[],'logs-poll':[]};lock=threading.Lock();processes=[]

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length',0)))
        action=self.path.rsplit('/',1)[-1]
        with lock:
            if action in hits:hits[action].append(time.monotonic())
        body=json.dumps({'task':None} if action=='poll' else {'request':None}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)

server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
    installed=json.loads(Path(r'C:\PokerSuite\Updater\agent.json').read_text(encoding='utf-8-sig'))
    config=folder/'test.json'
    config.write_text(json.dumps(dict(BaseUrl=f'http://127.0.0.1:{server.server_port}',MachineId=999997,
        SiteId=1,Token='local-test-token',TrustedKeys=[],Root=str(folder/'managed'),
        DecisionHealthUrl='http://127.0.0.1:1',ExpectedMac=installed['ExpectedMac'])))
    def launch(*args):
        p=subprocess.Popen([str(AGENT),*args,'--config',str(config)],creationflags=subprocess.CREATE_NO_WINDOW)
        processes.append(p);return p
    agent=launch()
    deadline=time.monotonic()+10
    while not hits['logs-poll'] and time.monotonic()<deadline:time.sleep(.1)
    assert hits['logs-poll'],'Installed collector did not start'
    helper=launch('--diagnostics-only')
    time.sleep(32)
    with lock:polls=list(hits['poll']);logs=list(hits['logs-poll'])
    assert 3<=len(polls)<=6,(len(polls),polls)
    assert all(b-a>=4.8 for a,b in zip(polls,polls[1:])),polls
    assert 2<=len(logs)<=3 and all(b-a>=14 for a,b in zip(logs,logs[1:])),logs
    agent.terminate();agent.wait(10)
    until=time.monotonic()+20
    while len(hits['logs-poll'])==len(logs) and time.monotonic()<until:time.sleep(.1)
    assert len(hits['logs-poll'])>len(logs),'Helper did not take over diagnostic polling'
    assert helper.poll() is None
    print(json.dumps({'sample_seconds':32,'updater_requests':len(polls),
        'diagnostic_requests_with_two_processes':len(logs),'collector_failover':True}))
finally:
    for p in processes:
        if p.poll() is None:p.terminate();p.wait(10)
    server.shutdown();server.server_close()
    shutil.rmtree(folder)
