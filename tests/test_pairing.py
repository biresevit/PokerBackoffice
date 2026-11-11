import base64,json,time,uuid
from datetime import datetime,timezone
import pytest
from cryptography.hazmat.primitives import serialization,hashes
from cryptography.hazmat.primitives.asymmetric import rsa,padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from backoffice.pairing import seal,mac,public_request,approve,lookup
from backoffice.db import connect,Database
from backoffice.store import Store,Context
from backoffice.validation import Error
from backoffice.updates import agent_request


def test_new_pairing_code_expires_after_two_hours(monkeypatch):
 from datetime import timedelta
 from backoffice import pairing
 stamp=datetime(2026,11,11,8,0)
 monkeypatch.setattr(pairing,'now',lambda:stamp)
 class FakeDB:
  def one(self,sql,*args):return {'value':0} if 'sp_getapplock' in sql else {'n':0}
  def execute(self,sql,*args):pass
 key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
 result=public_request(FakeDB(),'request',{'hostname':'TEST','macs':['02-11-22-33-44-55'],
  'public_key':key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()},'test')
 assert datetime.fromisoformat(result['expires'].removesuffix('Z'))==stamp+timedelta(hours=2)

def test_envelope_requires_device_private_key():
 key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
 envelope=seal(key.public_key(),{'secret':'test-runtime-secret'})
 assert 'test-runtime-secret' not in json.dumps(envelope)
 secret=key.decrypt(base64.b64decode(envelope['key']),padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
 data=AESGCM(secret).decrypt(base64.b64decode(envelope['nonce']),base64.b64decode(envelope['data']),b'PokerSuite-Pairing-v1')
 assert json.loads(data)=={'secret':'test-runtime-secret'}

def test_mac_normalization_and_validation():
 assert mac('02:90:1d:03:85:65')=='02-90-1D-03-85-65'
 with pytest.raises(Error):mac('invalid')

@pytest.mark.skipif(__import__('os').getenv('BACKOFFICE_TEST_SQL')!='1',reason='Opt-in rollback SQL test')
def test_pairing_approval_proof_scope_and_one_time_delivery(monkeypatch):
 conn=connect()
 try:
  db=Database(conn);subject='pairing-test-'+str(uuid.uuid4());key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
  pending=public_request(db,'request',{'hostname':'ISOLATED-TEST-PC','macs':['02-11-22-33-44-55'],'public_key':key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()},subject)
  def proof(action,key_override=None):
   stamp=int(time.time());nonce=uuid.uuid4().hex;sign=(key_override or key).sign(f"{pending['id']}:{action}:{stamp}:{nonce}".encode(),padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=32),hashes.SHA256())
   return {'id':pending['id'],'timestamp':stamp,'nonce':nonce,'signature':base64.b64encode(sign).decode()}
  first=proof('poll');assert public_request(db,'poll',first,'test')['status']=='pending'
  with pytest.raises(Error):public_request(db,'poll',first,'test')
  with pytest.raises(Error):public_request(db,'poll',proof('poll',rsa.generate_private_key(public_exponent=65537,key_size=3072)),'test')
  store=Store(db,Context(14004,'test',subject,'operator'))
  with pytest.raises(Error):lookup(store,1,{'code':pending['code']})
  db.execute("INSERT backoffice.SetupAdministrator(Provider,Subject) VALUES('test',%s)",subject)
  assert lookup(store,1,{'code':pending['code']})['hostname']=='ISOLATED-TEST-PC'
  master=AESGCM.generate_key(bit_length=256);nonce=__import__('secrets').token_bytes(12);monkeypatch.setenv('BACKOFFICE_PAIRING_KEY',base64.b64encode(master).decode())
  runtime={'pdecision':{'Database':{'ConnectionString':'test-only'}},'worker':{'SqlConnectionString':'test-only'}}
  profile=json.dumps({'nonce':base64.b64encode(nonce).decode(),'data':base64.b64encode(AESGCM(master).encrypt(nonce,json.dumps(runtime).encode(),b'1')).decode()})
  db.execute('UPDATE backoffice.SetupProfile SET EncryptedProfile=%s WHERE SiteId=1;IF @@ROWCOUNT=0 INSERT backoffice.SetupProfile(SiteId,EncryptedProfile) VALUES(1,%s)',profile,profile)
  release=str(db.one('SELECT TOP(1) ReleaseId FROM scheduler.UpdateRelease WHERE Enabled=1 ORDER BY PublishedUtc DESC')['ReleaseId'])
  approved=approve(store,1,{'id':pending['id'],'mac':'02-11-22-33-44-55','release_id':release,'capacity':15})
  reply=public_request(db,'poll',proof('poll'),'test');assert reply['status']=='approved' and 'test-only' not in json.dumps(reply)
  envelope=reply['envelope'];secret=key.decrypt(base64.b64decode(envelope['key']),padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
  delivered=json.loads(AESGCM(secret).decrypt(base64.b64decode(envelope['nonce']),base64.b64decode(envelope['data']),b'PokerSuite-Pairing-v1'))
  assert delivered['config']['MachineId']==approved['machine_id'];assert delivered['worker']==runtime['worker']
  cfg=delivered['config'];mid=cfg['MachineId']
  before=db.one('SELECT InstanceId,LastHeartbeatUtc,AppsHealthy FROM scheduler.MachineUpdateAgent WHERE MachineId=%s',mid)
  status=agent_request(db,mid,{'x-updater-token':cfg['Token']},{},'status')
  assert status['authenticated'] and status['machine_id']==mid and status['update']['status']=='queued'
  assert 'Token' not in json.dumps(status,default=str) and 'test-only' not in json.dumps(status,default=str)
  assert db.one('SELECT InstanceId,LastHeartbeatUtc,AppsHealthy FROM scheduler.MachineUpdateAgent WHERE MachineId=%s',mid)==before
  with pytest.raises(Error):agent_request(db,mid,{'x-updater-token':'x'*48},{},'status')
  assert public_request(db,'complete',proof('complete'),'test')['accepted']
  completed=lookup(store,1,{'code':pending['code']});assert completed['status']=='completed' and completed['machine_id']==mid
  assert public_request(db,'poll',proof('poll'),'test')['envelope'] is None
  # A completed device approval remains usable as proof of identity after
  # the short human pairing code expires. Missing local credentials can be
  # restored only when offline, with no live sessions or active installation.
  db.execute('UPDATE backoffice.DevicePairing SET ExpiresUtc=DATEADD(day,-2,SYSUTCDATETIME()) WHERE RequestId=%s',pending['id'])
  assert public_request(db,'poll',proof('poll'),'test')['device_status']['machine_id']==mid
  db.execute('UPDATE scheduler.MachineUpdateAgent SET LastHeartbeatUtc=SYSUTCDATETIME() WHERE MachineId=%s',mid)
  with pytest.raises(Error):public_request(db,'restore',proof('restore'),'test')
  db.execute('UPDATE scheduler.MachineUpdateAgent SET LastHeartbeatUtc=NULL WHERE MachineId=%s',mid)
  db.execute('UPDATE scheduler.MachineUpdateTask SET StartedUtc=SYSUTCDATETIME() WHERE MachineId=%s',mid)
  with pytest.raises(Error):public_request(db,'restore',proof('restore'),'test')
  db.execute("UPDATE scheduler.MachineUpdateTask SET Status='failed',CompletedUtc=SYSUTCDATETIME() WHERE MachineId=%s",mid)
  db.execute("UPDATE scheduler.UpdateRollout SET Status='paused' WHERE RolloutId=%s",approved['rollout_id'])
  restored=public_request(db,'restore',proof('restore'),'test');assert restored['retry_queued']
  envelope=restored['envelope'];secret=key.decrypt(base64.b64decode(envelope['key']),padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
  restored_cfg=json.loads(AESGCM(secret).decrypt(base64.b64decode(envelope['nonce']),base64.b64decode(envelope['data']),b'PokerSuite-Pairing-v1'))['config']
  assert restored_cfg['MachineId']==mid and restored_cfg['Token']!=cfg['Token']
  assert public_request(db,'restore',proof('restore'),'test')['envelope']==envelope
  assert agent_request(db,mid,{'x-updater-token':restored_cfg['Token']},{},'status')['authenticated']
  assert db.one('SELECT Status FROM scheduler.UpdateRollout WHERE RolloutId=%s',approved['rollout_id'])['Status']=='cancelled'
  assert db.one("SELECT COUNT(*) AS n FROM scheduler.MachineUpdateTask WHERE MachineId=%s AND Status='queued'",mid)['n']==1
  public_request(db,'complete',proof('complete'),'test')
  db.execute('UPDATE scheduler.MachineUpdateAgent SET Enabled=0 WHERE MachineId=%s',mid)
  with pytest.raises(Error):public_request(db,'poll',proof('poll'),'test')
  with pytest.raises(Error):approve(store,1,{'id':pending['id'],'mac':'02-11-22-33-44-55','release_id':release})
 finally:conn.rollback();conn.close()
