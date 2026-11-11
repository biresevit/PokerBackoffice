"""One-time, RSA-bound pairing. No runtime credential is returned in plaintext."""
import base64,hashlib,json,os,re,secrets,uuid
from datetime import datetime,timedelta,timezone
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding,rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from .validation import Error,integer
from .updates import Updates,guid,operator

def now():return datetime.now(timezone.utc).replace(tzinfo=None)
PAIRING_LIFETIME = timedelta(hours=2)
def b64(value):return base64.b64encode(value).decode()
def admin(store):
 if store.ctx.role!='operator' or not store.db.one('SELECT Subject FROM backoffice.SetupAdministrator WHERE Provider=%s AND Subject=%s',store.ctx.provider,store.ctx.subject):raise Error(403,'Main administrator approval is required')
def mac(value):
 raw=re.sub('[-: ]','',str(value)).upper()
 if not re.fullmatch('[0-9A-F]{12}',raw):raise Error(400,'Invalid MAC address')
 return '-'.join(raw[i:i+2] for i in range(0,12,2))
def profile(db,site):
 row=db.one('SELECT EncryptedProfile FROM backoffice.SetupProfile WHERE SiteId=%s',site)
 if not row:raise Error(409,'Administrator must provision this site runtime profile first')
 key=base64.b64decode(os.environ['BACKOFFICE_PAIRING_KEY'])
 value=json.loads(row['EncryptedProfile']);raw=AESGCM(key).decrypt(base64.b64decode(value['nonce']),base64.b64decode(value['data']),str(site).encode())
 return json.loads(raw)
def seal(public,data):
 key=AESGCM.generate_key(bit_length=256);nonce=secrets.token_bytes(12)
 ciphertext=AESGCM(key).encrypt(nonce,json.dumps(data,separators=(',',':')).encode(),b'PokerSuite-Pairing-v1')
 return {'key':b64(public.encrypt(key,padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))),'nonce':b64(nonce),'data':b64(ciphertext)}
def public_request(db,action,body,source):
 if action=='request':
  source=hashlib.sha256(source.encode()).hexdigest();stamp=now()
  # Transaction lock makes the public request quota atomic across API instances.
  lock=db.one("DECLARE @r int;EXEC @r=sys.sp_getapplock @Resource='PairingRateLimit',@LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=5000;SELECT @r AS value")
  if not lock or lock['value']<0:raise Error(429,'Setup is busy; retry shortly')
  count=db.one('SELECT COUNT(*) AS n FROM backoffice.DevicePairing WHERE CreatedUtc>%s AND SourceHash=%s',stamp-timedelta(minutes=10),source)['n']
  total=db.one('SELECT COUNT(*) AS n FROM backoffice.DevicePairing WHERE CreatedUtc>%s',stamp-timedelta(minutes=10))['n']
  if count>=5 or total>=200:raise Error(429,'Too many setup requests; retry in ten minutes')
  host=str(body.get('hostname','')).strip()
  if not host or len(host)>200:raise Error(400,'Invalid PC name')
  addresses=body.get('macs')
  if not isinstance(addresses,list) or not 1<=len(addresses)<=8:raise Error(400,'Provide physical adapter MAC addresses')
  addresses=list(dict.fromkeys(mac(x) for x in addresses))
  try:
   pem=body['public_key'];key=serialization.load_pem_public_key(pem.encode())
   if not isinstance(key,rsa.RSAPublicKey) or key.key_size!=3072:raise ValueError()
  except (KeyError,ValueError,TypeError,AttributeError):raise Error(400,'Invalid setup public key')
  db.execute("DELETE FROM backoffice.DevicePairing WHERE Status='pending' AND ExpiresUtc<%s",stamp-timedelta(days=1))
  db.execute('UPDATE backoffice.DevicePairing SET EnvelopeJson=NULL WHERE ExpiresUtc<%s',stamp)
  rid=str(uuid.uuid4());code=''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(10));expiry=stamp+PAIRING_LIFETIME
  db.execute('INSERT backoffice.DevicePairing(RequestId,Code,HostName,MacsJson,PublicKey,SourceHash,ExpiresUtc) VALUES(%s,%s,%s,%s,%s,%s,%s)',rid,code,host,json.dumps(addresses),pem,source,expiry)
  return {'id':rid,'code':code,'expires':expiry.isoformat()+'Z'}
 rid=guid(body.get('id'),'setup request');row=db.one('SELECT * FROM backoffice.DevicePairing WITH(UPDLOCK,HOLDLOCK) WHERE RequestId=%s',rid)
 if not row or (row['ExpiresUtc']<now() and row['Status']!='completed'):raise Error(410,'Setup request expired; generate a new pairing code')
 try:
  timestamp=int(body['timestamp']);nonce=body['nonce']
  if abs(datetime.now(timezone.utc).timestamp()-timestamp)>120 or not re.fullmatch('[a-f0-9]{32}',nonce) or nonce==row['LastNonce']:raise ValueError()
  key=serialization.load_pem_public_key(row['PublicKey'].encode())
  key.verify(base64.b64decode(body['signature'],validate=True),f'{rid}:{action}:{timestamp}:{nonce}'.encode(),padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=32),hashes.SHA256())
 except Exception:raise Error(401,'Invalid device proof')
 db.execute('UPDATE backoffice.DevicePairing SET LastNonce=%s WHERE RequestId=%s',nonce,rid)
 if row['Status']=='completed':
  binding=db.one('SELECT g.Enabled,g.SiteId,m.CustomerId,m.IsActive,m.MacAddress FROM scheduler.MachineUpdateAgent g JOIN dbo.CustomerMachine m ON m.MachineId=g.MachineId WHERE g.MachineId=%s',row['MachineId'])
  if not binding or not binding['Enabled'] or not binding['IsActive'] or binding['SiteId']!=row['SiteId'] or binding['CustomerId']!=row['CustomerId'] or binding['MacAddress'] not in json.loads(row['MacsJson']):raise Error(403,'This saved device approval is no longer valid; administrator recovery is required')
  if db.one("SELECT RequestId FROM backoffice.DevicePairing WHERE MachineId=%s AND CreatedUtc>%s AND Status IN ('approved','completed') AND RequestId<>%s",row['MachineId'],row['CreatedUtc'],rid):raise Error(403,'This saved device key was replaced by a newer administrator approval')
 if action=='restore':
  if row['Status']!='completed' or not row['MachineId']:raise Error(409,'This device has not completed administrator approval')
  if db.one("SELECT RequestId FROM backoffice.DevicePairing WHERE MachineId=%s AND CreatedUtc>%s AND Status IN ('approved','completed') AND RequestId<>%s",row['MachineId'],row['CreatedUtc'],rid):raise Error(403,'This device key was superseded by a newer administrator approval')
  enrolled=db.one('SELECT g.Enabled,g.SiteId,g.LastHeartbeatUtc,m.CustomerId,m.IsActive,m.MacAddress FROM scheduler.MachineUpdateAgent g JOIN dbo.CustomerMachine m ON m.MachineId=g.MachineId WHERE g.MachineId=%s',row['MachineId'])
  if not enrolled or not enrolled['Enabled'] or not enrolled['IsActive'] or enrolled['SiteId']!=row['SiteId'] or enrolled['CustomerId']!=row['CustomerId'] or enrolled['MacAddress'] not in json.loads(row['MacsJson']):raise Error(403,'Administrator recovery is required for this registration')
  if row['EnvelopeJson'] and row['ExpiresUtc']>now():return {'envelope':json.loads(row['EnvelopeJson'])}
  if enrolled['LastHeartbeatUtc'] and enrolled['LastHeartbeatUtc']>now()-timedelta(minutes=3):raise Error(409,'The existing updater is connected. Restore its original local enrollment files instead of replacing its credentials.')
  if db.one('SELECT TOP(1) EntryId FROM scheduler.Entry WHERE MachineId=%s AND IsOpen=1',row['MachineId']) or db.one('SELECT TOP(1) SessionId FROM scheduler.AccountSession WHERE MachineId=%s AND IsOpen=1',row['MachineId']):raise Error(409,'Finish or reconcile existing sessions before restoring this offline installation')
  if db.one('SELECT TaskId FROM scheduler.MachineUpdateTask WHERE MachineId=%s AND StartedUtc IS NOT NULL AND CompletedUtc IS NULL',row['MachineId']):raise Error(409,'An application update is still active; review that task before recovery')
  from .store import Store,Context
  store=Store(db,Context(row['CustomerId'],'device',rid,'operator'))
  runtime=profile(db,row['SiteId']);cfg=Updates(store).enroll(row['SiteId'],{'machine_id':row['MachineId']})
  envelope=seal(key,{'config':cfg,'pdecision':runtime['pdecision'],'worker':runtime['worker']})
  db.execute('UPDATE backoffice.DevicePairing SET EnvelopeJson=%s,ExpiresUtc=%s WHERE RequestId=%s',json.dumps(envelope),now()+PAIRING_LIFETIME,rid)
  retry_queued=False
  latest=db.one('SELECT TOP(1) t.Status,t.RolloutId,r.ReleaseId,r.Status AS RolloutStatus,g.CurrentReleaseId,v.Enabled FROM scheduler.MachineUpdateTask t JOIN scheduler.UpdateRollout r ON r.RolloutId=t.RolloutId JOIN scheduler.MachineUpdateAgent g ON g.MachineId=t.MachineId JOIN scheduler.UpdateRelease v ON v.ReleaseId=r.ReleaseId WHERE t.MachineId=%s ORDER BY r.CreatedUtc DESC',row['MachineId'])
  if latest and latest['Status']=='failed' and latest['RolloutStatus']=='paused' and not latest['CurrentReleaseId'] and latest['Enabled'] and not db.one("SELECT TaskId FROM scheduler.MachineUpdateTask WHERE RolloutId=%s AND Status NOT IN ('completed','cancelled','failed','rolled_back')",latest['RolloutId']):
   db.execute("UPDATE scheduler.UpdateRollout SET Status='cancelled',UpdatedUtc=SYSUTCDATETIME() WHERE RolloutId=%s",latest['RolloutId'])
   retry=str(uuid.uuid4())
   db.execute("INSERT scheduler.UpdateRollout(RolloutId,CustomerId,SiteId,ReleaseId,Status,NotBeforeUtc,RequestedBy) VALUES(%s,%s,%s,%s,'queued',SYSUTCDATETIME(),%s)",retry,row['CustomerId'],row['SiteId'],latest['ReleaseId'],'device-recovery:'+rid)
   db.execute("INSERT scheduler.MachineUpdateTask(TaskId,RolloutId,SiteId,MachineId,Position,Status) VALUES(%s,%s,%s,%s,0,'queued')",str(uuid.uuid4()),retry,row['SiteId'],row['MachineId'])
   retry_queued=True
  store.audit('setup.restore',row['MachineId'],{'request':rid,'retry_queued':retry_queued})
  return {'envelope':envelope,'retry_queued':retry_queued}
 if action=='complete':
  if row['Status'] not in ('approved','completed'):raise Error(409,'Setup is not approved')
  db.execute("UPDATE backoffice.DevicePairing SET Status='completed',EnvelopeJson=NULL WHERE RequestId=%s",rid)
  return {'accepted':True}
 result={'status':row['Status'],'machine_id':row['MachineId'],'site_id':row['SiteId'],'envelope':json.loads(row['EnvelopeJson']) if row['Status']=='approved' else None}
 if row['Status']=='completed':
  from .updates import machine_status
  result['device_status']=machine_status(db,row['MachineId'],{},verified_device=True)
 return result

def lookup(store,site,body):
 admin(store);store.site(site);code=re.sub('[ -]','',str(body.get('code',''))).upper()
 row=store.db.one("SELECT RequestId AS id,HostName AS hostname,MacsJson,Status AS status,ExpiresUtc AS expires,MachineId AS machine_id,CustomerId FROM backoffice.DevicePairing WHERE Code=%s AND ExpiresUtc>SYSUTCDATETIME()",code)
 if not row:raise Error(404,'Pairing code not found or expired')
 if row.pop('CustomerId') not in (None,store.ctx.customer_id):raise Error(403,'This PC was approved for another customer')
 row['macs']=json.loads(row.pop('MacsJson'));return row

def approve(store,site,body):
 admin(store);store.site(site);db=store.db;rid=guid(body.get('id'),'setup request')
 row=db.one('SELECT * FROM backoffice.DevicePairing WITH(UPDLOCK,HOLDLOCK) WHERE RequestId=%s',rid)
 if not row or row['ExpiresUtc']<now() or row['Status']!='pending':raise Error(409,'Pairing request expired or already approved')
 address=mac(body.get('mac'))
 if address not in json.loads(row['MacsJson']):raise Error(400,'Select an adapter reported by the setup')
 runtime=profile(db,site);capacity=integer(body.get('capacity',30),1,10000,field='capacity')
 release=guid(body.get('release_id'),'release')
 if not db.one('SELECT ReleaseId FROM scheduler.UpdateRelease WHERE ReleaseId=%s AND Enabled=1',release):raise Error(404,'Release not available')
 existing=db.one('SELECT m.MachineId,g.CurrentReleaseId,g.LastHeartbeatUtc FROM dbo.CustomerMachine m LEFT JOIN scheduler.MachineUpdateAgent g ON g.MachineId=m.MachineId WHERE m.MacAddress=%s',address)
 if existing and (existing['CurrentReleaseId'] or existing['LastHeartbeatUtc'] and existing['LastHeartbeatUtc']>now()-timedelta(minutes=3)):raise Error(409,'This PC already has a managed installation; use its existing updater')
 mid=db.one('EXEC backoffice.RegisterPairedMachine @CustomerId=%s,@SiteId=%s,@Mac=%s,@Host=%s,@Capacity=%s',store.ctx.customer_id,site,address,row['HostName'],capacity)['MachineId']
 if db.one("SELECT t.TaskId FROM scheduler.MachineUpdateTask t JOIN scheduler.UpdateRollout r ON r.RolloutId=t.RolloutId WHERE t.MachineId=%s AND t.Status NOT IN ('completed','cancelled','failed','rolled_back') AND r.Status IN ('queued','running','paused')",mid):raise Error(409,'This machine already has a pending installation or update. Review that task before approving another setup.')
 cfg=Updates(store).enroll(site,{'machine_id':mid})
 envelope=seal(serialization.load_pem_public_key(row['PublicKey'].encode()),{'config':cfg,'pdecision':runtime['pdecision'],'worker':runtime['worker']})
 db.execute("UPDATE backoffice.DevicePairing SET Status='approved',CustomerId=%s,SiteId=%s,MachineId=%s,EnvelopeJson=%s WHERE RequestId=%s",store.ctx.customer_id,site,mid,json.dumps(envelope),rid)
 rollout=str(uuid.uuid4())
 db.execute("INSERT scheduler.UpdateRollout(RolloutId,CustomerId,SiteId,ReleaseId,Status,NotBeforeUtc,RequestedBy) VALUES(%s,%s,%s,%s,'queued',SYSUTCDATETIME(),%s)",rollout,store.ctx.customer_id,site,release,store.ctx.subject)
 db.execute("INSERT scheduler.MachineUpdateTask(TaskId,RolloutId,SiteId,MachineId,Position,Status) VALUES(%s,%s,%s,%s,0,'queued')",str(uuid.uuid4()),rollout,site,mid)
 store.audit('setup.approve',mid,{'request':rid,'release':release})
 return {'machine_id':mid,'rollout_id':rollout}
