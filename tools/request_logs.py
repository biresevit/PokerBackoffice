"""Request machine diagnostics and download the verified ZIP using local operator access."""
import argparse,hashlib,json,os,sys,time
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'api'))
from backoffice.db import session
from backoffice.store import Store,Context
from backoffice.machine_logs import MachineLogs,MAX_BYTES


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--machine',type=int,required=True);parser.add_argument('--site',type=int,default=1)
    parser.add_argument('--customer',type=int,default=14004);parser.add_argument('--hours',type=int,default=24)
    parser.add_argument('--subject',default=os.getenv('BACKOFFICE_OPERATOR_SUBJECT'))
    parser.add_argument('--request-id');parser.add_argument('--wait-minutes',type=float,default=10)
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/machine-logs')
    args=parser.parse_args()
    with session() as db:
        members=db.rows("SELECT Provider,Subject FROM backoffice.Membership WHERE CustomerId=%s AND Role='operator' AND IsActive=1",args.customer)
        members=[m for m in members if not args.subject or m['Subject']==args.subject]
        if len(members)!=1:raise SystemExit('Specify --subject for one active operator membership on this customer.')
        ctx=Context(args.customer,members[0]['Provider'],members[0]['Subject'],'operator')
        rid=args.request_id or MachineLogs(Store(db,ctx)).create(args.site,args.machine,{'hours':args.hours})['id']
    print(json.dumps({'request_id':str(rid),'machine':args.machine}),flush=True)
    deadline=time.monotonic()+args.wait_minutes*60;last=None
    while True:
        with session() as db:
            service=MachineLogs(Store(db,ctx));items=service.list(args.site,args.machine)['items']
            row=next((x for x in items if str(x['id']).lower()==str(rid).lower()),None)
            if row is None:raise SystemExit('Request not found in this machine history.')
            if row['status']=='ready':download=service.download(args.site,args.machine,str(rid))
            else:download=None
        if row['status']!=last:print('Status: '+row['status'],flush=True);last=row['status']
        if download:break
        if row['status'] in ('failed','expired'):raise SystemExit(row['detail'] or row['status'])
        if time.monotonic()>=deadline:raise SystemExit('Request queued. Run again with --request-id '+str(rid)+' to download when ready.')
        time.sleep(10)
    args.output.mkdir(parents=True,exist_ok=True);target=args.output/Path(download['filename']).name;partial=target.with_suffix('.partial')
    try:
        digest=hashlib.sha256();size=0
        with requests.get(download['url'],stream=True,timeout=60,allow_redirects=False) as response:
            if response.status_code!=200:raise SystemExit('Log download failed; request a new download link.')
            with partial.open('wb') as f:
                for chunk in response.iter_content(256*1024):
                    size+=len(chunk)
                    if size>MAX_BYTES:raise SystemExit('Log download exceeded its size limit.')
                    digest.update(chunk);f.write(chunk)
        if size!=download['size_bytes'] or digest.hexdigest()!=download['sha256']:raise SystemExit('Log checksum did not match.')
        partial.replace(target);print(json.dumps({'downloaded':str(target.resolve()),'bytes':size,'sha256':digest.hexdigest()}))
    except requests.RequestException:
        raise SystemExit('Log download interrupted. Retry using the request ID; upload/download links are not printed.') from None
    finally:partial.unlink(missing_ok=True)


if __name__=='__main__':main()
