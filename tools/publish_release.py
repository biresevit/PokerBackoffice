"""Publish an immutable signed Windows application pair and updater bootstrap."""
import argparse,base64,hashlib,json,os,re,subprocess,uuid,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
from azure.storage.blob import BlobServiceClient,BlobSasPermissions,generate_blob_sas,ContentSettings
from azure.core.exceptions import ResourceExistsError
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa,padding
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'api'))
from backoffice.db import session


def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--label',required=True)
 parser.add_argument('--pdecision-dir',type=Path,default=ROOT.parent/'PDecision/obfuscation/dist')
 parser.add_argument('--controller-dir',type=Path,default=ROOT.parent/'PokerController/artifacts/fleet-package/PokerController')
 parser.add_argument('--pdecision-version',default='1.0.0.29')
 parser.add_argument('--controller-version',default='0.1.0+365faaa.updater1')
 args=parser.parse_args()
 if not re.fullmatch('[A-Za-z0-9._-]{1,100}',args.label):raise SystemExit('Invalid release label')
 with session() as db:
  if db.one('SELECT ReleaseId FROM scheduler.UpdateRelease WHERE Label=%s',args.label):raise SystemExit('This immutable release label already exists')
 keydir=Path(os.environ['LOCALAPPDATA'])/'PokerSuitePublisher'
 keydir.mkdir(parents=True,exist_ok=True)
 keyfile=keydir/'release-signing.pem'
 if not keyfile.exists():
  key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
  keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
  owner=subprocess.run(['whoami'],capture_output=True,text=True,check=True).stdout.strip()
  subprocess.run(['icacls',str(keydir),'/inheritance:r','/grant:r',owner+':(OI)(CI)F','SYSTEM:(OI)(CI)F'],capture_output=True,check=True)
 key=serialization.load_pem_private_key(keyfile.read_bytes(),password=None)
 public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
 info=args.controller_dir/'build-info.json'
 info.write_text(json.dumps({'controllerVersion':args.controller_version}),encoding='utf-8')
 output=ROOT/'artifacts/releases';output.mkdir(parents=True,exist_ok=True)
 package=output/(args.label+'.zip')
 for folder,exe in [(args.pdecision_dir,'PDecision.exe'),(args.controller_dir,'PokerController.exe')]:
  if not (folder/exe).exists():raise SystemExit(f'Missing application: {folder/exe}')
 with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
  for prefix,folder in [('pdecision',args.pdecision_dir),('controller',args.controller_dir)]:
   for path in sorted(folder.rglob('*')):
    if not path.is_file():continue
    if path.name.lower() in ('appsettings.json','authentication.txt','mapping.txt') or path.suffix.lower() in ('.pdb','.mdf','.ldf'):continue
    if path.is_symlink():raise RuntimeError('Release files cannot be symlinks')
    z.write(path,prefix+'/'+path.relative_to(folder).as_posix())
 rid=str(uuid.uuid4())
 manifest=json.dumps({'format':1,'releaseId':rid,'pdecisionVersion':args.pdecision_version,'controllerVersion':args.controller_version,
     'sha256':hashlib.sha256(package.read_bytes()).hexdigest(),'size':package.stat().st_size,'created':datetime.now(timezone.utc).isoformat()},sort_keys=True,separators=(',',':'))
 signature=base64.b64encode(key.sign(manifest.encode(),padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=32),hashes.SHA256())).decode()
 bootstrap=output/(args.label+'-updater.zip')
 agent=ROOT.parent/'PokerController/artifacts/updater-agent'
 with zipfile.ZipFile(bootstrap,'w',zipfile.ZIP_DEFLATED) as z:
  for path in sorted(agent.iterdir()):
   if path.is_file() and path.suffix!='.pdb':z.write(path,'agent/'+path.name)
  z.write(ROOT.parent/'PokerController/updater/Install-Updater.ps1','Install-Updater.ps1')
  z.writestr('README.txt','Download the machine enrollment JSON from Updates in the backoffice. Run Install-Updater.ps1 -ConfigPath <file> -ControllerRoot <existing PokerController folder>. The updater starts on user logon. Existing applications continue running until a rollout has drained their sessions.')
 raw=os.environ['StorageConnString'];values=dict(v.split('=',1) for v in raw.split(';') if '=' in v)
 service=BlobServiceClient.from_connection_string(raw);container=service.get_container_client('client-releases')
 try:container.create_container()
 except ResourceExistsError:pass
 urls=[]
 for file in (package,bootstrap):
  blob=container.get_blob_client(args.label+'/'+file.name)
  with file.open('rb') as stream:blob.upload_blob(stream,overwrite=False,content_settings=ContentSettings(content_type='application/zip',content_disposition='attachment; filename="'+file.name+'"'))
  sas=generate_blob_sas(service.account_name,container.container_name,blob.blob_name,account_key=values['AccountKey'],permission=BlobSasPermissions(read=True),expiry=datetime.now(timezone.utc)+timedelta(days=365),start=datetime.now(timezone.utc)-timedelta(minutes=5),protocol='https')
  urls.append(blob.url+'?'+sas)
 with session() as db:
  db.execute('INSERT scheduler.UpdateRelease(ReleaseId,Label,PDecisionVersion,PokerControllerVersion,ManifestJson,Signature,PublicKey,ArtifactUrl,BootstrapUrl) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',rid,args.label,args.pdecision_version,args.controller_version,manifest,signature,public,*urls)
 print(json.dumps({'release':args.label,'id':rid,'package_mb':round(package.stat().st_size/1024/1024,1),'sha256':json.loads(manifest)['sha256']}))

if __name__=='__main__':main()
