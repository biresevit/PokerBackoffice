"""Read existing scoped archives; return allowlisted counts, never raw log lines."""
import io
import json
import re
import zipfile
from collections import Counter

SIGNALS = ('CREDENTIAL_EXPIRED','LOGIN_REPLACED','INSUFFICIENT_CHIPS','INSUFFICIENT_FUNDS',
           'LOGIN_FAILED','AUTH_FAILED','CONNECTION_CLOSED','TimeoutError','ConnectionError',
           'SQLTransientConnectionError','join_failure_limit')
MAX_BYTES = 64*1024*1024


def summarize(blob, site_id, machine_id):
    if len(blob)>MAX_BYTES: raise ValueError('Archive too large')
    counts=Counter()
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        entries=z.infolist()
        if len(entries)>100 or sum(i.file_size for i in entries)>128*1024*1024:
            raise ValueError('Archive limits exceeded')
        info=z.getinfo('manifest.json')
        if info.file_size>128*1024: raise ValueError('Manifest too large')
        manifest=json.loads(z.read(info))
        if manifest.get('site_id')!=site_id or manifest.get('machine_id')!=machine_id:
            raise ValueError('Archive scope mismatch')
        files=0
        for i in entries:
            # Controller-only logs. PDecision hand/action logs are not relevant and may contain cards.
            if not i.filename.lower().startswith(('controller/','worker/')) or not i.filename.lower().endswith('.log'):
                continue
            if i.file_size>8*1024*1024: continue
            text=z.read(i).decode('utf-8',errors='replace')
            for code in SIGNALS:
                counts[code]+=len(re.findall(r'(?<![A-Za-z_])'+re.escape(code)+r'(?![A-Za-z_])',text))
            files+=1
    return {'captured_utc':manifest.get('captured_utc'), 'signals':dict(counts), 'files_scanned':files,
            'limitations':['Counts cover bounded archive tails, not necessarily the whole requested time range.',
                'Signals may repeat one incident. A zero count does not establish absence.',
                'Raw lines, account identities, secrets and hand data are never returned.']}


def read(db, scope, hours):
    from azure.storage.blob import BlobServiceClient
    import os
    connection=os.getenv('BACKOFFICE_DIAGNOSTICS_STORAGE') or os.getenv('StorageConnString')
    if not connection:return {'available':False,'reason':'Existing log archive storage is not configured'}
    rows=db.rows('''SELECT TOP(2) r.MachineId,r.BlobName,r.SizeBytes,r.CreatedUtc
        FROM backoffice.MachineLogRequest r
        JOIN dbo.CustomerMachine m ON m.MachineId=r.MachineId AND m.CustomerId=r.CustomerId
        WHERE r.CustomerId=%s AND r.SiteId=%s AND r.Status='ready'
        AND r.ExpiresUtc>SYSUTCDATETIME() AND r.CreatedUtc>=DATEADD(hour,-%s,SYSUTCDATETIME())
        ORDER BY r.CreatedUtc DESC''',scope.customer_id,scope.site_id,hours)
    results=[]
    with BlobServiceClient.from_connection_string(connection, connection_timeout=5, read_timeout=10, retry_total=0) as client:
        for row in rows:
            if not row['SizeBytes'] or row['SizeBytes']>MAX_BYTES:continue
            blob=client.get_blob_client('machine-diagnostics',row['BlobName'])
            if blob.get_blob_properties().size>MAX_BYTES:continue
            results.append(summarize(blob.download_blob(max_concurrency=1).readall(),scope.site_id,row['MachineId']))
    return {'archives':results,'limitations':['Reads existing completed unexpired archives only; never requests a new collection or logs in an account.']}
