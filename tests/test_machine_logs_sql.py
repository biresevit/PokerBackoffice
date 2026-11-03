"""Real request/claim SQL against connection-local temporary tables only."""
import os
from types import SimpleNamespace
import uuid

import pytest

from backoffice.db import connect,Database
from backoffice.machine_logs import MachineLogs,collector_request
from backoffice.validation import Error

pytestmark=pytest.mark.skipif(os.getenv('BACKOFFICE_TEST_SQL')!='1',reason='Opt-in SQL tests')


def test_request_claim_progress_download_and_stale_collector(monkeypatch):
    import backoffice.machine_logs as module
    monkeypatch.setattr(module,'machine_status',lambda db,mid,headers:{'site_id':1})
    conn=connect()
    class TemporaryDB(Database):
        def rows(self,q,*args):return super().rows(q.replace('backoffice.MachineLogRequest','#Logs').replace('scheduler.MachineUpdateAgent','#Agent'),*args)
        def execute(self,q,*args):return super().execute(q.replace('backoffice.MachineLogRequest','#Logs').replace('scheduler.MachineUpdateAgent','#Agent'),*args)
    class Blobs:
        def url(self,name,write=False):return 'https://unit.blob.core.windows.net/'+name
        def verify(self,*args):pass
    try:
        db=TemporaryDB(conn)
        db.execute('''CREATE TABLE #Logs(RequestId uniqueidentifier PRIMARY KEY,CustomerId int,SiteId int,MachineId int,RequestedBy nvarchar(200),Hours int,
            Status varchar(16) DEFAULT 'queued',CreatedUtc datetime2 DEFAULT SYSUTCDATETIME(),UpdatedUtc datetime2 DEFAULT SYSUTCDATETIME(),ExpiresUtc datetime2,
            ClaimToken uniqueidentifier,ClaimUntilUtc datetime2,BlobName nvarchar(250),SizeBytes bigint,Sha256 char(64),Detail nvarchar(1000));
            CREATE TABLE #Agent(MachineId int,LogCollectorVersion varchar(30),LogCollectorHeartbeatUtc datetime2);INSERT #Agent(MachineId) VALUES(19);''')
        store=SimpleNamespace(db=db,ctx=SimpleNamespace(customer_id=14004,subject='temporary-test',role='operator'),site=lambda sid:None,audit=lambda *a:None)
        service=MachineLogs(store,Blobs());rid=service.create(1,19,{'hours':6})['id']
        assert service.create(1,19,{'hours':6})['existing']
        work=collector_request(db,19,{}, {'collector_version':'test'},'logs-poll',Blobs())['request']
        assert work['id'].lower()==rid and work['hours']==6
        assert collector_request(db,19,{}, {},'logs-poll',Blobs())['request'] is None
        report=dict(id=rid,claim=work['claim'],phase='uploading')
        with pytest.raises(Error):collector_request(db,18,{},report,'logs-report',Blobs())
        db.execute('UPDATE #Logs SET ClaimUntilUtc=DATEADD(second,-1,SYSUTCDATETIME()) WHERE RequestId=%s',rid)
        replacement=collector_request(db,19,{}, {},'logs-poll',Blobs())['request']
        with pytest.raises(Error):collector_request(db,19,{},report,'logs-report',Blobs())
        report['claim']=replacement['claim']
        collector_request(db,19,{},report,'logs-report',Blobs())
        collector_request(db,19,{},dict(report,phase='ready',size_bytes=100,sha256='a'*64),'logs-report',Blobs())
        assert service.list(1,19)['items'][0]['status']=='ready'
        assert service.download(1,19,rid)['size_bytes']==100
        db.execute('UPDATE #Logs SET ExpiresUtc=DATEADD(second,-1,SYSUTCDATETIME()) WHERE RequestId=%s',rid)
        with pytest.raises(Error):service.download(1,19,rid)
    finally:conn.rollback();conn.close()
