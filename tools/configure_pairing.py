"""Provision a site profile and explicit main administrator. Never prints secrets."""
import argparse,base64,json,secrets,sys
from pathlib import Path
from datetime import datetime,timedelta,timezone
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from azure.storage.blob import BlobServiceClient,BlobSasPermissions,generate_blob_sas,ContentSettings
import os
from configure_azure import arm,RESOURCE
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'api'))
from backoffice.db import session
p=argparse.ArgumentParser();p.add_argument('--site',type=int,required=True);p.add_argument('--admin-subject',required=True);p.add_argument('--pdecision',type=Path,required=True);p.add_argument('--worker',type=Path,required=True);p.add_argument('--publish-setup',action='store_true');p.add_argument('--setup-version',default='1.0.5');a=p.parse_args()
settings=arm('POST',RESOURCE+'/listAppSettings',{})['properties']
key=base64.b64decode(settings['BACKOFFICE_PAIRING_KEY']) if settings.get('BACKOFFICE_PAIRING_KEY') else AESGCM.generate_key(bit_length=256)
nonce=secrets.token_bytes(12);profile={'pdecision':json.loads(a.pdecision.read_text(encoding='utf-8-sig')),'worker':json.loads(a.worker.read_text(encoding='utf-8-sig'))}
if not profile['pdecision'].get('Database',{}).get('ConnectionString'):raise SystemExit('PDecision runtime profile missing connection setting')
if not (profile['worker'].get('SCHEDULE_SQL_CONNECTION_STRING') or profile['worker'].get('SqlConnectionString')):raise SystemExit('Worker runtime profile missing connection setting')
encrypted=json.dumps({'nonce':base64.b64encode(nonce).decode(),'data':base64.b64encode(AESGCM(key).encrypt(nonce,json.dumps(profile).encode(),str(a.site).encode())).decode()})
with session() as db:
 if not db.one("SELECT Subject FROM backoffice.Membership WHERE Provider='aad' AND Subject=%s AND IsActive=1 AND Role='operator' AND CustomerId=(SELECT CustomerId FROM scheduler.Site WHERE SiteId=%s)",a.admin_subject,a.site):raise SystemExit('Administrator must already have operator access to this site customer')
 db.execute("IF NOT EXISTS(SELECT 1 FROM backoffice.SetupAdministrator WHERE Provider='aad' AND Subject=%s) INSERT backoffice.SetupAdministrator(Provider,Subject) VALUES('aad',%s)",a.admin_subject,a.admin_subject)
 db.execute('UPDATE backoffice.SetupProfile SET EncryptedProfile=%s,UpdatedUtc=SYSUTCDATETIME() WHERE SiteId=%s;IF @@ROWCOUNT=0 INSERT backoffice.SetupProfile(SiteId,EncryptedProfile) VALUES(%s,%s)',encrypted,a.site,a.site,encrypted)
settings['BACKOFFICE_PAIRING_KEY']=base64.b64encode(key).decode()
if a.publish_setup:
 service=BlobServiceClient.from_connection_string(os.environ['StorageConnString']);values=dict(x.split('=',1) for x in os.environ['StorageConnString'].split(';') if '=' in x)
 path=ROOT.parent/'PokerController/artifacts/setup/PokerSuite.Setup.exe';blob=service.get_blob_client('client-releases','setups/PokerSuite.Setup-'+a.setup_version+'.exe')
 with path.open('rb') as f:blob.upload_blob(f,overwrite=False,content_settings=ContentSettings(content_type='application/octet-stream',content_disposition='attachment; filename="PokerSuite.Setup.exe"'))
 sas=generate_blob_sas(service.account_name,'client-releases',blob.blob_name,account_key=values['AccountKey'],permission=BlobSasPermissions(read=True),expiry=datetime.now(timezone.utc)+timedelta(days=365),protocol='https')
 settings['BACKOFFICE_SETUP_URL']=blob.url+'?'+sas
arm('PUT',RESOURCE+'/config/appsettings',{'properties':settings})
print('Encrypted runtime profile and main administrator configured. Setup published:',a.publish_setup)
