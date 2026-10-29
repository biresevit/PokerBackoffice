"""Chat integration writes roll back and never contact a poker site."""
import os
import uuid
from datetime import datetime,timezone
from contextlib import contextmanager
import pytest
from backoffice.db import connect,Database
from backoffice.store import Store,Context
from backoffice.chat import Chat
from backoffice.validation import Error

pytestmark=pytest.mark.skipif(os.getenv('BACKOFFICE_TEST_SQL')!='1',reason='Opt-in SQL tests')


@pytest.fixture
def chat():
    conn=connect()
    try:
        db=Database(conn)
        # Isolated SQL transaction holds these rows until rollback; the live
        # worker cannot see or send the test outbox records.
        db.execute("UPDATE scheduler.MachineAssignment SET IsReady=1,LastHeartbeatUtc=SYSUTCDATETIME() WHERE SiteId=1 AND MachineId=1")
        epoch=db.one('SELECT WorkerEpoch FROM scheduler.MachineAssignment WHERE SiteId=1 AND MachineId=1')['WorkerEpoch']
        db.execute("""UPDATE scheduler.ChatAgent SET WorkerEpoch=%s,UpdatedUtc=SYSUTCDATETIME() WHERE SiteId=1 AND MachineId=1;
            IF @@ROWCOUNT=0 INSERT scheduler.ChatAgent(SiteId,MachineId,WorkerEpoch) VALUES(1,1,%s)""",epoch,epoch)
        store=Store(db,Context(14004,'test','chat-test','operator'))
        yield Chat(store)
    finally:
        conn.rollback();conn.close()


def test_chat_summary_send_idempotency_and_access(chat):
    summary=chat.summary(1)
    bot=next((b for t in summary['items'] for b in t['bots'] if b['chat_ready']),None)
    if not bot: pytest.skip('Needs a seated bot')
    body={'request_id':str(uuid.uuid4()),'entry_id':bot['entry_id'],'text':'Rollback test message - never sent'}
    sent=chat.send(1,bot['table_id'],body)
    assert chat.send(1,bot['table_id'],body)==sent
    assert chat.db.one('SELECT COUNT(*) AS n FROM scheduler.ChatCommand WHERE RequestId=%s',body['request_id'])['n']==1
    with pytest.raises(Error) as error:
        chat.send(1,bot['table_id'],{**body,'text':'different'})
    assert error.value.status==409
    viewer=Chat(Store(chat.db,Context(14004,'test','viewer','viewer')))
    with pytest.raises(Error) as error: viewer.send(1,bot['table_id'],body)
    assert error.value.status==403
    foreign=Chat(Store(chat.db,Context(1,'test','foreign','operator')))
    with pytest.raises(Error) as error: foreign.summary(1)
    assert error.value.status==404
    with pytest.raises(Error): chat.send(1,'not-this-table',{**body,'request_id':str(uuid.uuid4())})
    assert all(c['body'] for c in chat.messages(1,bot['table_id'],{})['commands'])


def test_human_notifications_are_personal_and_history_does_not_notify(chat):
    table='__chat_rollback_'+str(uuid.uuid4())[:8]
    for author,body,human,historical in [('Human','Hello',1,0),('monica','Hi',0,0),('Human','Old history',1,1)]:
        chat.db.execute('INSERT scheduler.ChatMessage(SiteId,TableId,EventKey,Author,Body,IsHuman,IsHistorical) VALUES(1,%s,%s,%s,%s,%s,%s)',table,uuid.uuid4().hex.ljust(64,'0'),author,body,human,historical)
    conversation=next(t for t in chat.summary(1)['items'] if t['table_id']==table)
    assert conversation['unread']==1
    messages=chat.messages(1,table,{})['items']
    chat.read(1,table,{'last_id':messages[-1]['id']})
    assert next(t for t in chat.summary(1)['items'] if t['table_id']==table)['unread']==0
    other=Chat(Store(chat.db,Context(14004,'test','another-user','viewer')))
    assert next(t for t in other.summary(1)['items'] if t['table_id']==table)['unread']==1
    chat.read(1,table,{'last_id':0})
    assert next(t for t in chat.summary(1)['items'] if t['table_id']==table)['unread']==0
    with pytest.raises(Error): chat.read(1,table,{'last_id':messages[-1]['id']+100000})


def test_worker_deduplication_classification_and_at_most_once_claim(chat):
    import sys
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'ScheduleController'))
    from schedule_controller.chat_repository import ChatRepository
    epoch=chat.db.one('SELECT WorkerEpoch FROM scheduler.MachineAssignment WHERE SiteId=1 AND MachineId=1')['WorkerEpoch']
    class Adapter:
        def one(self,sql,*args): return chat.db.one(sql.replace('?','%s'),*args)
        def execute(self,sql,*args): return chat.db.execute(sql.replace('?','%s'),*args)
    class Repo(ChatRepository):
        @contextmanager
        def transaction(self): yield Adapter()
    repo=Repo();repo.epoch=epoch
    table='__chat_worker_test'
    def message(author):
        return {'table_id':table,'event_key':uuid.uuid4().hex.ljust(64,'0'),'author':author,'body':'Test only',
                'posted':None,'received':datetime.now(timezone.utc),'historical':False}
    human=message('HumanRollbackTest');bot=message('monica')
    repo.chat_exchange([human,bot,human])
    rows=chat.db.rows('SELECT Author,IsHuman FROM scheduler.ChatMessage WHERE SiteId=1 AND TableId=%s',table)
    assert len(rows)==2
    assert {r['Author']:r['IsHuman'] for r in rows}=={'HumanRollbackTest':True,'monica':False}
    seated=next((b for t in chat.summary(1)['items'] for b in t['bots'] if b['chat_ready']),None)
    if seated:
        body={'request_id':str(uuid.uuid4()),'entry_id':seated['entry_id'],'text':'Never sent in test'}
        chat.send(1,seated['table_id'],body)
        claimed=repo.claim_chat()
        assert str(claimed['RequestId'])==body['request_id']
        repo.finish_chat(body['request_id'],'uncertain','No echo in test')
        next_claim=repo.claim_chat()
        assert not next_claim or str(next_claim['RequestId'])!=body['request_id']
    repo.epoch=uuid.uuid4()
    with pytest.raises(RuntimeError): repo.chat_exchange([])
