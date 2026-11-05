"""Customer-scoped, expiring manual control for one hero at one live table."""
import json
import re
import uuid
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from .validation import Error


def target_minor(value,scale=100):
    try:
        amount=Decimal(str(value))*scale
        if not amount.is_finite() or amount!=amount.to_integral_value() or not 0<amount<=10**14:raise ValueError()
        return int(amount)
    except (InvalidOperation,ValueError,TypeError):raise Error(400,'Enter a positive whole-chip amount.' if scale==1 else 'Enter a positive chip amount with at most two decimal places.')


def table_id_ok(value):
    """A tournament's playing table: a number on EvenBet, a UUID on BluffPoker."""
    if value.isdigit():return True
    try:return str(uuid.UUID(value))==value.lower()
    except ValueError:return False


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
        payload=json.loads(row['PayloadJson']) if row.get('PayloadJson') else {}
        row['ControlTableId']=str(payload.get('table_id') or '') if str(row['TableId']).startswith('T') else str(row['TableId'])
        if str(row['TableId']).startswith('T') and not table_id_ok(row['ControlTableId']):row['ControlTableId']=''
        return row

    def lock(self,row):
        if not row['ControlTableId']:raise Error(409,'Waiting for the tournament playing table.')
        resource=f"ManualTable:{row['SiteId']}:{row['BotAccountId']}:{row['ControlTableId']}"
        result=self.db.one("""DECLARE @r int;EXEC @r=sys.sp_getapplock @Resource=%s,
            @LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=5000;SELECT @r AS value""",resource)
        if not result or result['value']<0:raise Error(409,'Table control is busy. Try again.')

    def current(self,row):
        return self.db.one("""SELECT c.*,r.ExpiresUtc,a.WorkerEpoch AS CurrentEpoch FROM scheduler.ManualTableControl c
            JOIN scheduler.LiveViewRequest r ON r.RequestId=c.RequestId
            JOIN scheduler.MachineAssignment a ON a.SiteId=c.SiteId AND a.MachineId=c.MachineId
            WHERE c.SiteId=%s AND c.BotAccountId=%s AND c.TableId=%s""",row['SiteId'],row['BotAccountId'],row['ControlTableId'])

    def fresh(self,row):
        now=datetime.now(timezone.utc).replace(tzinfo=None)
        if row['ExpiresUtc']<=now or row['Status'] not in ('requested','active'):raise Error(409,'The live view expired. Open it again.')
        if not row['CapturedUtc'] or (now-row['CapturedUtc']).total_seconds()>5:raise Error(409,'Waiting for a fresh table snapshot')
        p=json.loads(row['PayloadJson'])
        if not p.get('manual',{}).get('supported'):raise Error(409,'Update PokerController on this machine to enable manual control.')
        tournament=str(row['TableId']).startswith('T')
        if tournament and (p.get('amount_unit')!='tournament_chips' or p.get('manual',{}).get('amount_scale')!=1):raise Error(409,'Update PokerController to use tournament chip amounts for manual control.')
        entry=self.db.one("""SELECT TOP(1) e.WorkerEpoch FROM scheduler.Entry e
            JOIN scheduler.MachineAssignment a ON a.SiteId=e.SiteId AND a.MachineId=e.MachineId
            JOIN scheduler.LiveViewRequest r ON r.RequestId=%s
            WHERE e.SiteId=%s AND e.BotAccountId=%s AND e.TableId=%s AND e.MachineId=%s
              AND e.IsOpen=1 AND e.WorkerEpoch=a.WorkerEpoch AND a.IsReady=1
              AND a.LastHeartbeatUtc>=DATEADD(second,-180,SYSUTCDATETIME())
              AND r.Status IN ('requested','active') AND r.ExpiresUtc>SYSUTCDATETIME()
              AND (LEFT(e.TableId,1)<>'T' OR e.PlayTableId=%s)""",row['RequestId'],row['SiteId'],row['BotAccountId'],row['TableId'],row['MachineId'],row['ControlTableId'])
        if not entry:raise Error(409,'The hero left or changed this table. Open a new live view.')
        return p,entry

    def mode(self,site_id,request_id,body):
        row=self.scope(site_id,request_id)
        enabled=body.get('enabled')
        if type(enabled) is not bool:raise Error(400,'Manual control must be on or off')
        if enabled and str(row['TableId']).startswith('T') and body.get('amount_unit')!='tournament_chips':raise Error(409,'Refresh this live window to enable tournament manual control.')
        self.lock(row);current=self.current(row)
        if current and current['Enabled'] and str(current['WorkerEpoch'])==str(current['CurrentEpoch']) and current['ExpiresUtc']>datetime.now(timezone.utc).replace(tzinfo=None) and str(current['RequestId'])!=str(row['RequestId']):
            raise Error(409,'Another live window controls this hero. Turn control off there first.')
        if enabled:
            _,entry=self.fresh(row)
            if current:
                self.db.execute("""UPDATE scheduler.ManualTableControl SET Enabled=1,RequestId=%s,MachineId=%s,
                    WorkerEpoch=%s,UpdatedUtc=SYSUTCDATETIME() WHERE SiteId=%s AND BotAccountId=%s AND TableId=%s""",row['RequestId'],row['MachineId'],entry['WorkerEpoch'],site_id,row['BotAccountId'],row['ControlTableId'])
            else:
                self.db.execute('INSERT scheduler.ManualTableControl(SiteId,BotAccountId,TableId,MachineId,WorkerEpoch,RequestId,Enabled) VALUES(%s,%s,%s,%s,%s,%s,1)',site_id,row['BotAccountId'],row['ControlTableId'],row['MachineId'],entry['WorkerEpoch'],row['RequestId'])
        elif current:
            self.db.execute('UPDATE scheduler.ManualTableControl SET Enabled=0,UpdatedUtc=SYSUTCDATETIME() WHERE SiteId=%s AND BotAccountId=%s AND TableId=%s',site_id,row['BotAccountId'],row['ControlTableId'])
        self.store.audit('tables.manual.mode',str(row['RequestId']),{'enabled':enabled,'account':row['BotAccountId'],'table':row['TableId']})
        return {'enabled':enabled}

    def action(self,site_id,request_id,body):
        row=self.scope(site_id,request_id);self.lock(row)
        if str(row['TableId']).startswith('T') and body.get('amount_unit')!='tournament_chips':raise Error(409,'Refresh this live window to use tournament chip amounts.')
        current=self.current(row);p,entry=self.fresh(row)
        if not current or not current['Enabled'] or str(current['RequestId'])!=str(row['RequestId']) or str(current['WorkerEpoch'])!=str(entry['WorkerEpoch']):raise Error(409,'Enable manual control for this hero first.')
        o=p.get('manual',{});key=body.get('turn_key','');action=body.get('action')
        if action in ('sit_out','sit_in'):return self.table_command(site_id,row,entry,o,action)
        if not re.fullmatch('[0-9a-f]{64}',str(key)) or key!=o.get('turn_key'):raise Error(409,'The turn changed. Wait for the current action controls.')
        if action not in o.get('actions',[]):raise Error(400,'That action is not available on this turn.')
        if self.db.one('SELECT TurnKey FROM scheduler.TableActionClaim WHERE SiteId=%s AND BotAccountId=%s AND TableId=%s AND TurnKey=%s',site_id,row['BotAccountId'],row['ControlTableId'],key):raise Error(409,'An action has already been submitted for this turn.')
        # A refused action (failed/expired) does not use up the turn; the operator may choose again.
        existing=self.db.one("""SELECT ActionId,Status FROM scheduler.ManualTableAction WHERE RequestId=%s AND TurnKey=%s
            AND Status IN ('queued','submitted','sent','uncertain')""",row['RequestId'],key)
        if existing:return {'action_id':str(existing['ActionId']),'status':existing['Status']}
        scale=1 if str(row['TableId']).startswith('T') else 100
        amount=target_minor(body.get('amount'),scale) if action in ('bet','raise') else None
        if amount is not None and not o['min_target_minor']<=amount<=o['max_target_minor']:
            digits=0 if scale==1 else 2
            raise Error(400,f"{'Bet' if action=='bet' else 'Raise to'} must be between {o['min_target_minor']/scale:.{digits}f} and {o['max_target_minor']/scale:.{digits}f}.")
        aid=str(uuid.uuid4())
        self.db.execute('''INSERT scheduler.ManualTableAction(ActionId,RequestId,SiteId,BotAccountId,TableId,MachineId,WorkerEpoch,TurnKey,Action,TargetMinor)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',aid,row['RequestId'],site_id,row['BotAccountId'],row['ControlTableId'],row['MachineId'],entry['WorkerEpoch'],key,action,amount)
        self.store.audit('tables.manual.action',aid,{'action':action,'target_minor':amount,'turn':key})
        return {'action_id':aid,'status':'queued'}

    def table_command(self,site_id,row,entry,o,action):
        """Sit out next hand / I'm back. Not tied to a turn, so each gets its own random key."""
        if not o.get('table_commands'):raise Error(409,'Update PokerController on this machine to sit out or return from the live view.')
        if action=='sit_in' and not o.get('away'):raise Error(409,'The hero is not sitting out.')
        if action=='sit_out' and (o.get('away') or o.get('sit_out_pending')):raise Error(409,'The hero is already sitting out.')
        if self.db.one("""SELECT ActionId FROM scheduler.ManualTableAction WHERE RequestId=%s AND Action IN ('sit_out','sit_in')
            AND Status IN ('queued','submitted')""",row['RequestId']):raise Error(409,'The previous sit-out or I’m back command is still being sent.')
        aid=str(uuid.uuid4())
        self.db.execute('''INSERT scheduler.ManualTableAction(ActionId,RequestId,SiteId,BotAccountId,TableId,MachineId,WorkerEpoch,TurnKey,Action,TargetMinor)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL)''',aid,row['RequestId'],site_id,row['BotAccountId'],row['ControlTableId'],row['MachineId'],entry['WorkerEpoch'],uuid.uuid4().hex+uuid.uuid4().hex,action)
        self.store.audit('tables.manual.action',aid,{'action':action})
        return {'action_id':aid,'status':'queued'}

    def status(self,site_id,request_id):
        row=self.scope(site_id,request_id);c=self.current(row)
        active=bool(row['Status'] in ('requested','active') and c and c['Enabled'] and str(c['WorkerEpoch'])==str(c['CurrentEpoch']) and c['ExpiresUtc']>datetime.now(timezone.utc).replace(tzinfo=None))
        mine=bool(c and str(c['RequestId'])==str(row['RequestId']))
        latest=self.db.one("""SELECT TOP(1) Status AS status,ResultText AS detail,TurnKey AS turn_key FROM scheduler.ManualTableAction
            WHERE RequestId=%s AND Action NOT IN ('sit_out','sit_in') ORDER BY CreatedUtc DESC""",row['RequestId'])
        command=self.db.one("""SELECT TOP(1) Action AS action,Status AS status,ResultText AS detail,
            DATEDIFF(second,UpdatedUtc,SYSUTCDATETIME()) AS age FROM scheduler.ManualTableAction
            WHERE RequestId=%s AND Action IN ('sit_out','sit_in') ORDER BY CreatedUtc DESC""",row['RequestId'])
        return {'enabled':active and mine,'other_window':active and not mine,'last_action':latest,'last_command':command}
