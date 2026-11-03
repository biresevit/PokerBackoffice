from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import uuid

import pytest

from backoffice.machine_logs import MachineLogs,collector_request
from backoffice.validation import Error


class DB:
    def __init__(self):self.writes=[];self.exists=True;self.row=None;self.pending=None
    def one(self,sql,*args):
        if 'dbo.CustomerMachine m JOIN' in sql:return {'MachineId':19} if self.exists else None
        if 'sp_getapplock' in sql:return {'value':0}
        if "Status IN ('queued','collecting','uploading')" in sql:return self.pending
        if 'backoffice.MachineLogRequest' in sql:return self.row
        raise AssertionError(sql)
    def execute(self,sql,*args):self.writes.append((sql,args))


class Blobs:
    def __init__(self):self.checked=[]
    def url(self,name,write=False):return 'https://example.blob.core.windows.net/logs/'+name+('?upload' if write else '?read')
    def verify(self,*args):self.checked.append(args)


def env(role='operator'):
    db=DB();audits=[]
    store=SimpleNamespace(db=db,ctx=SimpleNamespace(role=role,customer_id=14004,subject='owner'),site=lambda s:None,audit=lambda *a:audits.append(a))
    return MachineLogs(store,Blobs()),db,audits


def test_operator_request_is_scoped_deduplicated_and_audited():
    s,db,audit=env();r=s.create(1,19,{'hours':6})
    insert=next(args for sql,args in db.writes if 'INSERT backoffice.MachineLogRequest' in sql)
    assert insert[1:6]==(14004,1,19,'owner',6) and insert[-1]==f'14004/19/{r["id"]}.zip' and audit
    db.pending={'id':r['id']};before=len(db.writes)
    assert s.create(1,19,{'hours':24})['existing']
    assert len(db.writes)==before


def test_viewer_and_foreign_machine_cannot_request():
    s,db,_=env('viewer')
    with pytest.raises(Error) as e:s.create(1,19,{})
    assert e.value.status==403 and not db.writes
    db.exists=False
    with pytest.raises(Error) as e:s.download(1,19,str(uuid.uuid4()))
    assert e.value.status==404


@pytest.mark.parametrize('hours',[0,169,True,'bad'])
def test_invalid_history_is_rejected(hours):
    s,db,_=env()
    with pytest.raises(Error):s.create(1,19,{'hours':hours})
    assert not db.writes


def test_download_requires_ready_and_uses_stored_blob_path():
    s,db,_=env();rid=str(uuid.uuid4());db.row={'Status':'collecting'}
    with pytest.raises(Error):s.download(1,19,rid)
    db.row={'Status':'ready','BlobName':'14004/19/'+rid+'.zip','SizeBytes':12,'Sha256':'a'*64}
    assert s.download(1,19,rid)['url'].endswith(rid+'.zip?read')


def test_collection_claim_is_bound_to_machine_and_token(monkeypatch):
    import backoffice.machine_logs as module
    monkeypatch.setattr(module,'machine_status',lambda db,mid,headers:{'site_id':1})
    _,db,_=env();blobs=Blobs();rid=str(uuid.uuid4());token=str(uuid.uuid4())
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    db.row={'RequestId':rid,'ClaimToken':token,'ExpiresUtc':now+timedelta(days=7),
        'ClaimUntilUtc':now+timedelta(minutes=5),'Status':'collecting','BlobName':'14004/19/'+rid+'.zip'}
    body={'id':rid,'claim':str(uuid.uuid4()),'phase':'ready','size_bytes':10,'sha256':'a'*64}
    with pytest.raises(Error) as e:collector_request(db,19,{},body,'logs-report',blobs)
    assert e.value.status==409 and not blobs.checked
    result=collector_request(db,19,{},dict(body,claim=token),'logs-report',blobs)
    assert result['accepted'] and blobs.checked==[(db.row['BlobName'],10,'a'*64)]
