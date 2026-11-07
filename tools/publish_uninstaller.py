"""Publish PokerSuite.Uninstall.exe and link it on the Machines page (BACKOFFICE_UNINSTALL_URL). Never prints secrets.

Build first (from PokerController):
  dotnet publish updater\\uninstall\\PokerSuite.Uninstall.csproj -c Release -r win-x64 --self-contained true
      -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -o artifacts\\uninstall
"""
import argparse,os,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
from azure.storage.blob import BlobServiceClient,BlobSasPermissions,generate_blob_sas,ContentSettings
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from configure_azure import arm,RESOURCE

p=argparse.ArgumentParser();p.add_argument('--version',required=True);args=p.parse_args()
if not args.version or not all(c.isdigit() or c=='.' for c in args.version):raise SystemExit('Invalid version')
exe=ROOT.parent/'PokerController/artifacts/uninstall/PokerSuite.Uninstall.exe'
if not exe.is_file():raise SystemExit(f'Build the uninstaller first: {exe}')
raw=os.environ['StorageConnString'];values=dict(v.split('=',1) for v in raw.split(';') if '=' in v)
service=BlobServiceClient.from_connection_string(raw)
blob=service.get_blob_client('client-releases','setups/PokerSuite.Uninstall-'+args.version+'.exe')
with exe.open('rb') as f:blob.upload_blob(f,overwrite=False,content_settings=ContentSettings(content_type='application/octet-stream',
    content_disposition='attachment; filename="PokerSuite.Uninstall.exe"'))
sas=generate_blob_sas(service.account_name,'client-releases',blob.blob_name,account_key=values['AccountKey'],permission=BlobSasPermissions(read=True),
    expiry=datetime.now(timezone.utc)+timedelta(days=365),protocol='https')
settings=arm('POST',RESOURCE+'/listAppSettings')['properties'];settings['BACKOFFICE_UNINSTALL_URL']=blob.url+'?'+sas
arm('PUT',RESOURCE+'/config/appsettings',{'properties':settings})
print('Uninstaller published:',args.version)
