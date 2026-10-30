"""Customer-scoped, expiring manual control for one hero at one live table."""
import json
import re
import uuid
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from .validation import Error


def target_minor(value):
    try:
        amount=Decimal(str(value))*100
        if not amount.is_finite() or amount!=amount.to_integral_value() or not 0<amount<=10**14:raise ValueError()
        return int(amount)
    except (InvalidOperation,ValueError,TypeError):raise Error(400,'Enter a positive chip amount with at most two decimal places.')


class Manual:
    def __init__(self,store):self.store=store;self.db=store.db

    def scope(self,site_id,request_id):
        self.store.site(site_id)
        if self.store.ctx.role!='operator':raise Error(403,'Manual control requires operator access')
        try:request_id=str(uuid.UUID(str(request_id)))
        except ValueError:raise Error(400,'Invalid live-view request')
        row=self.db.one("""SELECT r.*,s.CapturedUtc,s.PayloadJson FROM scheduler.LiveViewRequest r
            LEFT JOIN scheduler.LiveTableSnapshot s ON s.RequestId=r.RequestId
            WHERE r.RequestId=%s AND r.SiteId=%s AND r.RequestedBy=%s""",request_id,site_id,self.store.ctx.subject)
        if not row:raise Error(404,'Live view was not found')
        return row

    def lock(self,row):
        resource=f"ManualTable:{row['SiteId']}:{row['BotAccountId']}:{row['TableId']}"
        result=self.db.one("""DECLARE @r int;EXEC @r=sys.sp_getapplock @Resource=%s,
            @LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=5000;SELECT @r AS value""",resource)
        if not result or result['value']<0:raise Error(409,'Table control is busy. Try again.')

    def current(self,row):
        return self.db.one("""SELECT c.*,r.ExpiresUtc,a.WorkerEpoch AS CurrentEpoch FROM scheduler.ManualTableControl c
            JOIN scheduler.LiveViewRequest r ON r.RequestId=c.RequestId
            JOIN scheduler.MachineAssignment a ON a.SiteId=c.SiteId AND a.MachineId=c.MachineId
            WHERE c.SiteId=%s AND c.BotAccountId=%s AND c.TableId=%s""",row['SiteId'],row['BotAccountId'],row['TableId'])

    def fresh(self,row):
        now=datetime.now(timezone.utc).replace(tzinfo=None)
        if row['ExpiresUtc']<=now or row['Status'] not in ('requested','active'):raise Error(409,'The live view expired. Open it again.')
        if not row['CapturedUtc'] or (now-row['CapturedUtc']).total_seconds()>5:raise Error(409,'Waiting for a fresh table snapshot')
        p=json.loads(row['PayloadJson'])
        if not p.get('manual',{}).get('supported'):raise Error(409,'Update PokerController on this machine to enable manual control.')
        entry=self.db.one("""SELECT TOP(1) e.WorkerEpoch FROM scheduler.Entry e
            JOIN scheduler.MachineAssignment a ON a.SiteId=e.SiteId AND a.MachineId=e.MachineId
            WHERE e.SiteId=%s AND e.BotAccountId=%s AND e.TableId=%s AND e.MachineId=%s
              AND e.IsOpen=1 AND e.WorkerEpoch=a.WorkerEpoch AND a.IsReady=1
              AND a.LastHeartbeatUtc>=DATEADD(second,-180,SYSUTCDATETIME())""",row['SiteId'],row['BotAccountId'],row['TableId'],row['MachineId'])
        if not entry:raise Error(409,'The selected hero is no longer active on this machine.')
        return p,entry

    def mode(self,site_id,request_id,body):
        row=self.scope(site_id,request_id)
        enabled=body.get('enabled')
        if type(enabled) is not bool:raise Error(400,'Manual control must be on or off')
        self.lock(row);current=self.current(row)
        if current and current['Enabled'] and str(current['WorkerEpoch'])==str(current['CurrentEpoch']) and current['ExpiresUtc']>datetime.now(timezone.utc).replace(tzinfo=None) and str(current['RequestId'])!=str(row['RequestId']):
            raise Error(409,'Another live window controls this hero. Turn control off there first.')
        if enabled:
            _,entry=self.fresh(row)
            if current:
                self.db.execute("""UPDATE scheduler.ManualTableControl SET Enabled=1,RequestId=%s,MachineId=%s,
                    WorkerEpoch=%s,UpdatedUtc=SYSUTCDATETIME() WHERE SiteId=%s AND BotAccountId=%s AND TableId=%s""",row['RequestId'],row['MachineId'],entry['WorkerEpoch'],site_id,row['BotAccountId'],row['TableId'])
            else:
                self.db.execute('INSERT scheduler.ManualTableControl(SiteId,BotAccountId,TableId,MachineId,WorkerEpoch,RequestId,Enabled) VALUES(%s,%s,%s,%s,%s,%s,1)',site_id,row['BotAccountId'],row['TableId'],row['MachineId'],entry['WorkerEpoch'],row['RequestId'])
        elif current:
            self.db.execute('UPDATE scheduler.ManualTableControl SET Enabled=0,UpdatedUtc=SYSUTCDATETIME() WHERE SiteId=%s AND BotAccountId=%s AND TableId=%s',site_id,row['BotAccountId'],row['TableId'])
        self.store.audit('tables.manual.mode',str(row['RequestId']),{'enabled':enabled,'account':row['BotAccountId'],'table':row['TableId']})
        return {'enabled':enabled}

    def action(self,site_id,request_id,body):
        row=self.scope(site_id,request_id);self.lock(row)
        current=self.current(row);p,entry=self.fresh(row)
        if not current or not current['Enabled'] or str(current['RequestId'])!=str(row['RequestId']) or str(current['WorkerEpoch'])!=str(entry['WorkerEpoch']):raise Error(409,'Enable manual control for this hero first.')
        o=p.get('manual',{});key=body.get('turn_key','');action=body.get('action')
        if not re.fullmatch('[0-9a-f]{64}',str(key)) or key!=o.get('turn_key'):raise Error(409,'The turn changed. Wait for the current action controls.')
        if action not in o.get('actions',[]):raise Error(400,'That action is not available on this turn.')
        if self.db.one('SELECT TurnKey FROM scheduler.TableActionClaim WHERE SiteId=%s AND BotAccountId=%s AND TableId=%s AND TurnKey=%s',site_id,row['BotAccountId'],row['TableId'],key):raise Error(409,'An action has already been submitted for this turn.')
        existing=self.db.one('SELECT ActionId,Status FROM scheduler.ManualTableAction WHERE RequestId=%s AND TurnKey=%s',row['RequestId'],key)
        if existing:return {'action_id':str(existing['ActionId']),'status':existing['Status']}
        amount=target_minor(body.get('amount')) if action in ('bet','raise') else None
        if amount is not None and not o['min_target_minor']<=amount<=o['max_target_minor']:raise Error(400,'Bet/raise total is outside the current table limits.')
        aid=str(uuid.uuid4())
        self.db.execute('''INSERT scheduler.ManualTableAction(ActionId,RequestId,SiteId,BotAccountId,TableId,MachineId,WorkerEpoch,TurnKey,Action,TargetMinor)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',aid,row['RequestId'],site_id,row['BotAccountId'],row['TableId'],row['MachineId'],entry['WorkerEpoch'],key,action,amount)
        self.store.audit('tables.manual.action',aid,{'action':action,'target_minor':amount,'turn':key})
        return {'action_id':aid,'status':'queued'}

    def status(self,site_id,request_id):
        row=self.scope(site_id,request_id);c=self.current(row)
        active=bool(c and c['Enabled'] and str(c['WorkerEpoch'])==str(c['CurrentEpoch']) and c['ExpiresUtc']>datetime.now(timezone.utc).replace(tzinfo=None))
        mine=bool(c and str(c['RequestId'])==str(row['RequestId']))
        latest=self.db.one('SELECT TOP(1) Status AS status,ResultText AS detail,TurnKey AS turn_key FROM scheduler.ManualTableAction WHERE RequestId=%s ORDER BY CreatedUtc DESC',row['RequestId'])
        return {'enabled':active and mine,'other_window':active and not mine,'last_action':latest}
