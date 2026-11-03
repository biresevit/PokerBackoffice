"""Customer-scoped diagnostic requests with machine-bound claims and single-blob SAS URLs."""
from datetime import datetime,timedelta,timezone
import os,re,uuid

from .validation import Error,integer
from .updates import guid,machine_status

CONTAINER='machine-diagnostics'
MAX_BYTES=64*1024*1024


class Blobs:
    def __init__(self):
        from azure.storage.blob import BlobServiceClient
        connection=os.environ.get('BACKOFFICE_DIAGNOSTICS_STORAGE') or os.environ.get('StorageConnString')
        if not connection:raise Error(503,'Diagnostic storage is not configured')
        self.client=BlobServiceClient.from_connection_string(connection)
        self.key=dict(x.split('=',1) for x in connection.split(';') if '=' in x)['AccountKey']
    def url(self,name,write=False):
        from azure.storage.blob import BlobSasPermissions,generate_blob_sas
        now=datetime.now(timezone.utc)
        sas=generate_blob_sas(self.client.account_name,CONTAINER,name,account_key=self.key,
            permission=BlobSasPermissions(create=write,write=write,read=not write),
            start=now-timedelta(minutes=2),expiry=now+timedelta(minutes=15),protocol='https')
        return self.client.get_blob_client(CONTAINER,name).url+'?'+sas
    def verify(self,name,size,digest):
        import hashlib
        blob=self.client.get_blob_client(CONTAINER,name)
        props=blob.get_blob_properties()
        if props.size!=size or props.size>MAX_BYTES:raise Error(409,'Uploaded log size does not match')
        checksum=hashlib.sha256()
        for chunk in blob.download_blob().chunks():checksum.update(chunk)
        if checksum.hexdigest()!=digest:raise Error(409,'Uploaded logs failed the checksum check')


class MachineLogs:
    def __init__(self,store,blobs=None):self.store=store;self.db=store.db;self._blobs=blobs
    @property
    def blobs(self):
        if self._blobs is None:self._blobs=Blobs()
        return self._blobs
    def machine(self,sid,mid):
        self.store.site(sid)
        row=self.db.one('''SELECT m.MachineId FROM dbo.CustomerMachine m JOIN scheduler.MachineAssignment a ON a.MachineId=m.MachineId
            WHERE m.MachineId=%s AND m.CustomerId=%s AND a.SiteId=%s AND m.IsActive=1''',mid,self.store.ctx.customer_id,sid)
        if not row:raise Error(404,'Machine not found')
    def list(self,sid,mid):
        self.machine(sid,mid)
        self.db.execute("UPDATE backoffice.MachineLogRequest SET Status='expired' WHERE MachineId=%s AND ExpiresUtc<=SYSUTCDATETIME() AND Status<>'expired'",mid)
        return {'items':self.db.rows('''SELECT TOP(30) RequestId AS id,Status AS status,Hours AS hours,CreatedUtc AS created,
            ExpiresUtc AS expires,SizeBytes AS size_bytes,Detail AS detail FROM backoffice.MachineLogRequest
            WHERE SiteId=%s AND MachineId=%s AND CustomerId=%s ORDER BY CreatedUtc DESC''',sid,mid,self.store.ctx.customer_id)}
    def create(self,sid,mid,body):
        self.machine(sid,mid)
        if self.store.ctx.role!='operator':raise Error(403,'Your account has view-only access')
        hours=integer(body.get('hours',24),1,168,'log history hours')
        # Serializes duplicate browser clicks and concurrent CLI requests on the same PC.
        lock=self.db.one("DECLARE @r int; EXEC @r=sys.sp_getapplock @Resource=%s,@LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=5000; SELECT @r AS value",f'MachineLogs:{mid}')
        if not lock or lock['value']<0:raise Error(409,'Log requests are busy; try again')
        pending=self.db.one("SELECT RequestId AS id FROM backoffice.MachineLogRequest WHERE MachineId=%s AND Status IN ('queued','collecting','uploading') AND ExpiresUtc>SYSUTCDATETIME()",mid)
        if pending:return {'id':str(pending['id']),'existing':True}
        self.blobs  # Fail before queuing when storage is unavailable.
        rid=str(uuid.uuid4());name=f'{self.store.ctx.customer_id}/{mid}/{rid}.zip'
        self.db.execute('''INSERT backoffice.MachineLogRequest(RequestId,CustomerId,SiteId,MachineId,RequestedBy,Hours,ExpiresUtc,BlobName)
            VALUES(%s,%s,%s,%s,%s,%s,DATEADD(day,7,SYSUTCDATETIME()),%s)''',rid,self.store.ctx.customer_id,sid,mid,self.store.ctx.subject,hours,name)
        self.store.audit('machines.logs.request',rid,{'machine':mid,'hours':hours})
        return {'id':rid,'existing':False}
    def download(self,sid,mid,rid):
        self.machine(sid,mid)
        row=self.db.one('''SELECT Status,BlobName,SizeBytes,Sha256 FROM backoffice.MachineLogRequest
            WHERE RequestId=%s AND SiteId=%s AND MachineId=%s AND CustomerId=%s AND ExpiresUtc>SYSUTCDATETIME()''',guid(rid),sid,mid,self.store.ctx.customer_id)
        if not row:raise Error(404,'Log request not found or expired')
        if row['Status']!='ready':raise Error(409,'Logs are not ready for download')
        self.store.audit('machines.logs.download',rid,{'machine':mid})
        return {'url':self.blobs.url(row['BlobName']),'size_bytes':row['SizeBytes'],'sha256':row['Sha256'],
                'filename':f'machine-{mid}-logs-{guid(rid)}.zip'}


def collector_request(db,mid,headers,body,action,blobs=None):
    identity=machine_status(db,mid,headers)  # Validates enrollment, active customer and machine; does not alter updater identity.
    db.execute('UPDATE scheduler.MachineUpdateAgent SET LogCollectorVersion=%s,LogCollectorHeartbeatUtc=SYSUTCDATETIME() WHERE MachineId=%s',str(body.get('collector_version',''))[:30],mid)
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    if action=='logs-poll':
        row=db.one('''SELECT TOP(1) * FROM backoffice.MachineLogRequest WITH(UPDLOCK,READPAST,ROWLOCK)
            WHERE MachineId=%s AND SiteId=%s AND ExpiresUtc>SYSUTCDATETIME()
              AND (Status='queued' OR (Status IN ('collecting','uploading') AND ClaimUntilUtc<SYSUTCDATETIME())) ORDER BY CreatedUtc''',mid,identity['site_id'])
        if not row:return {'request':None}
        token=str(uuid.uuid4())
        db.execute("UPDATE backoffice.MachineLogRequest SET Status='collecting',ClaimToken=%s,ClaimUntilUtc=DATEADD(minute,15,SYSUTCDATETIME()),UpdatedUtc=SYSUTCDATETIME(),Detail='Collecting diagnostic logs.' WHERE RequestId=%s",token,row['RequestId'])
        return {'request':{'id':str(row['RequestId']),'claim':token,'hours':row['Hours'],'upload_url':(blobs or Blobs()).url(row['BlobName'],write=True),'max_bytes':MAX_BYTES}}
    row=db.one('''SELECT * FROM backoffice.MachineLogRequest WITH(UPDLOCK,HOLDLOCK)
        WHERE RequestId=%s AND MachineId=%s AND SiteId=%s''',guid(body.get('id')),mid,identity['site_id'])
    if not row or str(row['ClaimToken']).lower()!=guid(body.get('claim')) or row['ExpiresUtc']<=now or not row['ClaimUntilUtc'] or row['ClaimUntilUtc']<=now:raise Error(409,'Log collection claim expired')
    phase=body.get('phase')
    if row['Status']=='ready' and phase=='ready':return {'accepted':True}
    if row['Status'] not in ('collecting','uploading') or phase not in ('uploading','ready','failed'):raise Error(409,'Invalid log collection transition')
    size=digest=None
    if phase=='ready':
        size=integer(body.get('size_bytes'),1,MAX_BYTES,'log size');digest=body.get('sha256','')
        if not re.fullmatch('[a-f0-9]{64}',str(digest)):raise Error(400,'Invalid log checksum')
        (blobs or Blobs()).verify(row['BlobName'],size,digest)
    detail={'uploading':'Uploading ZIP archive.','ready':'Logs ready for download.','failed':'Collection failed; see the updater log.'}[phase]
    # Collector errors are fixed phrases, never exception bodies containing credentials or URLs.
    db.execute('''UPDATE backoffice.MachineLogRequest SET Status=%s,SizeBytes=COALESCE(%s,SizeBytes),Sha256=COALESCE(%s,Sha256),
        Detail=%s,UpdatedUtc=SYSUTCDATETIME() WHERE RequestId=%s''',phase,size,digest,detail,row['RequestId'])
    return {'accepted':True}
