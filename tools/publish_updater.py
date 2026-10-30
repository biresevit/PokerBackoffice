"""Publish a new initial-installer version without changing signed app releases."""
import argparse,os,sys,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
from azure.storage.blob import BlobServiceClient,BlobSasPermissions,generate_blob_sas,ContentSettings
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'api'))
from backoffice.db import session

p=argparse.ArgumentParser();p.add_argument('--version',required=True);args=p.parse_args()
if not all(c.isdigit() or c=='.' for c in args.version):raise SystemExit('Invalid version')
source=ROOT.parent/'PokerController/artifacts/updater-agent'
output=ROOT/'artifacts/releases'/('updater-'+args.version+'.zip')
with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
 for file in source.iterdir():
  if file.is_file() and file.suffix!='.pdb':z.write(file,'agent/'+file.name)
 z.write(ROOT.parent/'PokerController/updater/Install-Updater.ps1','Install-Updater.ps1')
 z.writestr('README.txt','Download the enrollment JSON for this PC from the Updates page. Run Install-Updater.ps1 -ConfigPath <file> -ControllerRoot <existing PokerController folder>. The agent starts at user logon. Do not reuse one PC enrollment on another PC.')
raw=os.environ['StorageConnString'];values=dict(v.split('=',1) for v in raw.split(';') if '=' in v)
service=BlobServiceClient.from_connection_string(raw);blob=service.get_blob_client('client-releases','updaters/'+output.name)
with output.open('rb') as stream:blob.upload_blob(stream,overwrite=False,content_settings=ContentSettings(content_type='application/zip',content_disposition='attachment; filename="'+output.name+'"'))
sas=generate_blob_sas(service.account_name,'client-releases',blob.blob_name,account_key=values['AccountKey'],permission=BlobSasPermissions(read=True),expiry=datetime.now(timezone.utc)+timedelta(days=365),start=datetime.now(timezone.utc)-timedelta(minutes=5),protocol='https')
with session() as db:db.execute('UPDATE scheduler.UpdateRelease SET BootstrapUrl=%s WHERE Enabled=1',blob.url+'?'+sas)
print('Updater installer published:',args.version)
