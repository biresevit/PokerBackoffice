"""Operator-created and operator-stopped account sessions."""
import random
import uuid
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from .updates import operator
from .validation import Error


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_input(value,zone,label):
    """Parse a datetime-local field entered in the site's timezone into naive UTC."""
    try:parsed=datetime.strptime(str(value),'%Y-%m-%dT%H:%M')
    except ValueError:raise Error(400,f'{label} must be a valid date and time')
    return parsed.replace(tzinfo=zone).astimezone(timezone.utc).replace(tzinfo=None)


def optional_id(value,label):
    if value in (None,'','any'):return None
    try:return int(value)
    except (TypeError,ValueError):raise Error(400,f'Invalid {label}')


class Sessions:
    def __init__(self,store):self.store=store;self.db=store.db

    def machines(self,site_id):
        return self.db.rows("""SELECT a.MachineId AS id,COALESCE(x.HostName,m.Description) AS name,a.WorkerEpoch AS epoch,
            a.MaxEntries AS capacity,
            (SELECT COUNT(*) FROM scheduler.Entry e WHERE e.SiteId=a.SiteId AND e.MachineId=a.MachineId AND e.IsOpen=1) AS entries,
            CONVERT(bit,CASE WHEN a.IsEnabled=1 AND a.IsReady=1 AND a.MaintenanceTaskId IS NULL AND a.WorkerEpoch IS NOT NULL
                AND a.LastHeartbeatUtc>=DATEADD(second,-180,SYSUTCDATETIME()) THEN 1 ELSE 0 END) AS available
            FROM scheduler.MachineAssignment a JOIN dbo.CustomerMachine m ON m.MachineId=a.MachineId
            LEFT JOIN backoffice.MachineMetadata x ON x.MachineId=a.MachineId
            WHERE a.SiteId=%s AND m.CustomerId=%s ORDER BY name""",site_id,self.store.ctx.customer_id)

    def accounts(self,site_id):
        return self.db.rows("""SELECT p.BotAccountId AS id,b.Username AS username,
            p.SessionMinMinutes AS min_minutes,p.SessionMaxMinutes AS max_minutes,
            CONVERT(bit,CASE WHEN EXISTS(SELECT 1 FROM scheduler.AccountSession s WHERE s.BotAccountId=p.BotAccountId AND s.IsOpen=1)
                THEN 1 ELSE 0 END) AS in_session,
            CONVERT(bit,CASE WHEN prior.ActualEndUtc IS NOT NULL
                AND DATEADD(minute,p.SessionCooldownMinutes,prior.ActualEndUtc)>SYSUTCDATETIME() THEN 1 ELSE 0 END) AS cooling_down
            FROM scheduler.AccountPolicy p JOIN dbo.BotAccount b ON b.BotAccountId=p.BotAccountId
            OUTER APPLY(SELECT TOP(1) x.ActualEndUtc FROM scheduler.AccountSession x
                WHERE x.BotAccountId=p.BotAccountId AND x.IsOpen=0 ORDER BY x.ActualEndUtc DESC) prior
            WHERE p.SiteId=%s AND p.DeletedUtc IS NULL AND p.IsEnabled=1 AND p.IsSynthetic=0 AND b.IsActive=1
                AND p.CredentialRef IS NOT NULL
            ORDER BY b.Username""",site_id)

    def options(self,site_id):
        site=self.store.site(site_id);zone=ZoneInfo(site['timezone'])
        return {'accounts':self.accounts(site_id),
                'machines':[{k:v for k,v in m.items() if k!='epoch'} for m in self.machines(site_id)],
                'now_local':datetime.now(zone).strftime('%Y-%m-%dT%H:%M'),'timezone':site['timezone']}

    def lock_account(self,aid):
        # Same lock the scheduler takes before creating a join, so a manual session can't race
        # a scheduler-created session for the same account.
        self.db.one('SELECT BotAccountId FROM scheduler.AccountLease WITH(UPDLOCK,HOLDLOCK) WHERE BotAccountId=%s',aid)

    def create(self,site_id,body):
        site=operator(self.store,site_id);zone=ZoneInfo(site['timezone']);now=utcnow()
        start=local_input(body.get('start'),zone,'Start') if body.get('start') else now
        # The form defaults to "now"; tolerate it going stale while the dialog stays open.
        if start<now-timedelta(minutes=15):raise Error(400,'Start time is in the past')
        start=max(start,now)
        end=local_input(body.get('end'),zone,'End')
        if end<=start+timedelta(minutes=1):raise Error(400,'End must be at least one minute after the start')
        if end-start>timedelta(hours=24):raise Error(400,'A manual session can last at most 24 hours')
        account_id=optional_id(body.get('account_id'),'bot');machine_id=optional_id(body.get('machine_id'),'machine')
        accounts={a['id']:a for a in self.accounts(site_id)}
        if account_id is None:
            eligible=[a for a in accounts.values() if not a['in_session'] and not a['cooling_down']]
            if not eligible:raise Error(409,'No bot is available: every enabled bot is in a session or cooling down')
            account=random.SystemRandom().choice(eligible)
        else:
            account=accounts.get(account_id)
            if not account:raise Error(404,'That bot is not enabled for this site')
        machines=[m for m in self.machines(site_id) if m['available']]
        if machine_id is None:
            if not machines:raise Error(409,'No machine is online and ready')
            most_free=max(m['capacity']-m['entries'] for m in machines)
            machine=random.SystemRandom().choice([m for m in machines if m['capacity']-m['entries']==most_free])
        else:
            machine=next((m for m in machines if m['id']==machine_id),None)
            if not machine:raise Error(409,'That machine is not online and ready')
        self.lock_account(account['id'])
        if self.db.one('SELECT SessionId FROM scheduler.AccountSession WHERE BotAccountId=%s AND IsOpen=1',account['id']):
            raise Error(409,f"{account['username']} already has an open session")
        session_id=str(uuid.uuid4())
        self.db.execute("""INSERT scheduler.AccountSession(SessionId,SiteId,BotAccountId,MachineId,WorkerEpoch,
            StartedUtc,PlannedEndUtc,IsOpen,IsManual,RequestedBy) VALUES(%s,%s,%s,%s,%s,%s,%s,1,1,%s)""",
            session_id,site_id,account['id'],machine['id'],machine['epoch'],start,end,self.store.ctx.subject)
        self.store.audit('sessions.create',session_id,{'account':account['id'],'machine':machine['id'],'start':start,'end':end})
        return {'id':session_id,'bot':account['username'],'machine':machine['name'] or machine['id'],'start':start,'end':end}

    def stop(self,site_id,session_id):
        operator(self.store,site_id)
        try:session_id=str(uuid.UUID(str(session_id)))
        except ValueError:raise Error(400,'Invalid session')
        row=self.db.one('SELECT BotAccountId FROM scheduler.AccountSession WHERE SessionId=%s AND SiteId=%s',session_id,site_id)
        if not row:raise Error(404,'Session not found')
        self.lock_account(row['BotAccountId'])
        row=self.db.one('SELECT IsOpen,StartedUtc FROM scheduler.AccountSession WITH(UPDLOCK) WHERE SessionId=%s',session_id)
        if not row['IsOpen']:raise Error(409,'This session has already ended')
        if self.db.one('SELECT TOP(1) EntryId FROM scheduler.Entry WHERE SessionId=%s',session_id):
            # The PC worker owns sessions it has joined tables for and rewrites their open state, so
            # end it through the scheduler: tables are left normally and the worker closes the session.
            self.db.execute("""UPDATE scheduler.AccountSession SET EndReason='stopped_by_operator',
                PlannedEndUtc=CASE WHEN PlannedEndUtc>SYSUTCDATETIME() THEN SYSUTCDATETIME() ELSE PlannedEndUtc END
                WHERE SessionId=%s""",session_id)
            status='leaving_tables'
        else:
            self.db.execute("""UPDATE scheduler.AccountSession SET IsOpen=0,EndReason='stopped_by_operator',
                ActualEndUtc=CASE WHEN StartedUtc>SYSUTCDATETIME() THEN StartedUtc ELSE SYSUTCDATETIME() END
                WHERE SessionId=%s""",session_id)
            status='stopped'
        self.store.audit('sessions.stop',session_id,{'status':status})
        return {'status':status}
