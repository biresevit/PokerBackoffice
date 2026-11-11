"""Customer-scoped table chat and explicitly requested bot replies."""
from __future__ import annotations
import uuid
from .validation import Error,integer


class Chat:
    def __init__(self,store):
        self.store,self.db,self.ctx=store,store.db,store.ctx

    def _scope(self,site_id):
        return self.store.site(site_id)

    def summary(self,site_id):
        site=self._scope(site_id)
        bots=self.db.rows("""SELECT e.EntryId AS entry_id,e.BotAccountId AS account_id,b.Username AS bot,
            COALESCE(e.PlayTableId,e.TableId) AS table_id,e.MachineId AS machine_id,
            CASE WHEN a.IsReady=1 AND a.LastHeartbeatUtc>=DATEADD(second,-180,SYSUTCDATETIME())
                 AND ca.WorkerEpoch=a.WorkerEpoch AND ca.UpdatedUtc>=DATEADD(second,-30,SYSUTCDATETIME())
                 THEN CONVERT(bit,1) ELSE CONVERT(bit,0) END AS chat_ready
            FROM scheduler.Entry e JOIN dbo.BotAccount b ON b.BotAccountId=e.BotAccountId
            JOIN scheduler.MachineAssignment a ON a.SiteId=e.SiteId AND a.MachineId=e.MachineId AND a.WorkerEpoch=e.WorkerEpoch
            LEFT JOIN scheduler.ChatAgent ca ON ca.SiteId=a.SiteId AND ca.MachineId=a.MachineId
            WHERE e.SiteId=%s AND e.IsOpen=1 AND e.Status IN ('seated','sitting_out','draining')
            ORDER BY b.Username""",site_id)
        rows=self.db.rows("""WITH conversations AS(
                SELECT TableId FROM scheduler.ChatMessage WHERE SiteId=%s
                UNION SELECT COALESCE(PlayTableId,TableId) FROM scheduler.Entry WHERE SiteId=%s AND IsOpen=1 AND Status IN ('seated','sitting_out','draining'))
            SELECT c.TableId AS table_id,COALESCE(t.TableName,c.TableId) AS name,
                latest.MessageId AS latest_id,latest.Author AS author,latest.Body AS body,latest.ReceivedUtc AS received,
                (SELECT COUNT(*) FROM scheduler.ChatMessage m WHERE m.SiteId=%s AND m.TableId=c.TableId
                    AND m.IsHuman=1 AND m.IsHistorical=0 AND m.MessageId>COALESCE(r.LastMessageId,0)) AS unread
            FROM conversations c LEFT JOIN scheduler.LobbyTable t ON t.SiteId=%s AND t.TableId=c.TableId
            LEFT JOIN backoffice.ChatReadState r ON r.SiteId=%s AND r.TableId=c.TableId AND r.Provider=%s AND r.Subject=%s
            OUTER APPLY(SELECT TOP(1) MessageId,Author,Body,ReceivedUtc FROM scheduler.ChatMessage m
                WHERE m.SiteId=%s AND m.TableId=c.TableId ORDER BY MessageId DESC) latest
            ORDER BY latest.MessageId DESC,c.TableId""",site_id,site_id,site_id,site_id,site_id,self.ctx.provider,self.ctx.subject,site_id)
        for row in rows:
            row['bots']=[{**b,'entry_id':str(b['entry_id'])} for b in bots if b['table_id']==row['table_id']]
        latest=self.db.one("""SELECT TOP(1) m.MessageId AS id,m.TableId AS table_id,m.Author AS author,
                COALESCE(t.TableName,m.TableId) AS table_name
            FROM scheduler.ChatMessage m LEFT JOIN scheduler.LobbyTable t ON t.SiteId=m.SiteId AND t.TableId=m.TableId
            WHERE m.SiteId=%s AND m.IsHuman=1 AND m.IsHistorical=0 ORDER BY m.MessageId DESC""",site_id)
        bluffpoker=site.get('platform')=='BluffPokerPlatform'
        return {'items':rows,'unread':sum(r['unread'] for r in rows),'latest_human':latest,
                'max_message_length':300 if bluffpoker else 2000,'server_history':not bluffpoker}

    def messages(self,site_id,table_id,query):
        self._scope(site_id)
        if not table_id or len(table_id)>80: raise Error(400,'Invalid table')
        before=integer(query.get('before',9223372036854775807),1,9223372036854775807,'message cursor')
        rows=self.db.rows("""SELECT TOP(100) MessageId AS id,Author AS author,Body AS body,
            PostedUtc AS posted,ReceivedUtc AS received,IsHuman AS is_human,IsHistorical AS historical
            FROM scheduler.ChatMessage WHERE SiteId=%s AND TableId=%s AND MessageId<%s ORDER BY MessageId DESC""",site_id,table_id,before)
        rows.reverse()
        commands=self.db.rows("""SELECT TOP(20) c.RequestId AS id,b.Username AS bot,c.Body AS body,
            CASE WHEN c.Status='queued' AND c.ExpiresUtc<=SYSUTCDATETIME() THEN 'expired'
                 WHEN c.Status='claimed' AND c.UpdatedUtc<DATEADD(second,-30,SYSUTCDATETIME()) THEN 'uncertain'
                 ELSE c.Status END AS status,c.ResultText AS detail,c.CreatedUtc AS created
            FROM scheduler.ChatCommand c JOIN scheduler.Entry e ON e.EntryId=c.EntryId
            JOIN dbo.BotAccount b ON b.BotAccountId=e.BotAccountId
            WHERE c.SiteId=%s AND COALESCE(c.TableId,e.PlayTableId,e.TableId)=%s ORDER BY c.CreatedUtc DESC""",site_id,table_id)
        for c in commands: c['id']=str(c['id'])
        return {'items':rows,'commands':commands,'before':rows[0]['id'] if len(rows)==100 else None}

    def read(self,site_id,table_id,body):
        self._scope(site_id)
        if not table_id or len(table_id)>80: raise Error(400,'Invalid table')
        last=integer(body.get('last_id'),0,9223372036854775807,'message')
        maximum=self.db.one('SELECT COALESCE(MAX(MessageId),0) AS id FROM scheduler.ChatMessage WHERE SiteId=%s AND TableId=%s',site_id,table_id)['id']
        if last>maximum: raise Error(400,'Invalid read position')
        self.db.execute("""UPDATE backoffice.ChatReadState WITH(UPDLOCK,HOLDLOCK)
            SET LastMessageId=CASE WHEN LastMessageId<%s THEN %s ELSE LastMessageId END
            WHERE SiteId=%s AND TableId=%s AND Provider=%s AND Subject=%s;
            IF @@ROWCOUNT=0 INSERT backoffice.ChatReadState(SiteId,TableId,Provider,Subject,LastMessageId) VALUES(%s,%s,%s,%s,%s)""",
            last,last,site_id,table_id,self.ctx.provider,self.ctx.subject,site_id,table_id,self.ctx.provider,self.ctx.subject,last)
        return {'read':True}

    def send(self,site_id,table_id,body):
        site=self._scope(site_id)
        if not table_id or len(table_id)>80: raise Error(400,'Invalid table')
        if self.ctx.role!='operator': raise Error(403,'Your account has view-only access')
        try:
            request_id=str(uuid.UUID(str(body.get('request_id'))))
            entry_id=str(uuid.UUID(str(body.get('entry_id'))))
        except (ValueError,AttributeError): raise Error(400,'Invalid chat request')
        text=body.get('text')
        maximum=300 if site.get('platform')=='BluffPokerPlatform' else 2000
        if not isinstance(text,str) or not text.strip() or len(text.strip().encode("utf-16-le"))>maximum*2 or '\x00' in text:
            raise Error(400,f'Enter a message of 1 to {maximum} characters')
        text=text.strip()
        prior=self.db.one("SELECT RequestId,EntryId,TableId,Body,RequestedBy,Provider FROM scheduler.ChatCommand WHERE RequestId=%s AND SiteId=%s",request_id,site_id)
        if prior:
            if (str(prior['EntryId']).lower()!=entry_id or prior['Body']!=text or prior['RequestedBy']!=self.ctx.subject
                    or prior['Provider']!=self.ctx.provider or prior.get('TableId') not in (None,table_id)):
                raise Error(409,'This request ID was already used')
            return {'request_id':request_id,'accepted':True}
        entry=self.db.one("""SELECT e.MachineId,e.WorkerEpoch FROM scheduler.Entry e WITH(UPDLOCK,HOLDLOCK)
            JOIN scheduler.MachineAssignment a ON a.SiteId=e.SiteId AND a.MachineId=e.MachineId AND a.WorkerEpoch=e.WorkerEpoch
            JOIN scheduler.ChatAgent ca ON ca.SiteId=a.SiteId AND ca.MachineId=a.MachineId AND ca.WorkerEpoch=a.WorkerEpoch
            WHERE e.SiteId=%s AND e.EntryId=%s AND COALESCE(e.PlayTableId,e.TableId)=%s AND e.IsOpen=1
                AND e.Status IN ('seated','sitting_out','draining') AND a.IsReady=1
                AND a.LastHeartbeatUtc>=DATEADD(second,-180,SYSUTCDATETIME())
                AND ca.UpdatedUtc>=DATEADD(second,-30,SYSUTCDATETIME())""",site_id,entry_id,table_id)
        if not entry: raise Error(409,'This bot is not connected to chat at this table. The machine needs the updated PokerController worker.')
        if self.db.one("SELECT RequestId FROM scheduler.ChatCommand WHERE SiteId=%s AND EntryId=%s AND Status IN ('queued','claimed') AND ExpiresUtc>SYSUTCDATETIME()",site_id,entry_id):
            raise Error(409,'A message for this bot and table is still being sent')
        self.db.execute("""INSERT scheduler.ChatCommand(RequestId,SiteId,EntryId,TableId,MachineId,WorkerEpoch,Body,RequestedBy,Provider)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",request_id,site_id,entry_id,table_id,entry['MachineId'],entry['WorkerEpoch'],text,self.ctx.subject,self.ctx.provider)
        self.store.audit('chat.send',request_id,{'entry_id':entry_id,'table_id':table_id})
        return {'request_id':request_id,'accepted':True}
