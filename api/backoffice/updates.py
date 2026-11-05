"""Operator-controlled rollouts and machine-bound updater authentication."""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import hashlib,hmac,secrets,uuid
from .validation import Error,integer

PUBLIC_URL='https://lively-rock-032158003.4.azurestaticapps.net'


def guid(value,field='ID'):
    try:return str(uuid.UUID(str(value)))
    except (ValueError,TypeError,AttributeError):raise Error(400,f'Invalid {field}')


def operator(store,site_id):
    site=store.site(site_id)
    if store.ctx.role!='operator':raise Error(403,'Your account has view-only access')
    return site


class Updates:
    def __init__(self,store):self.store=store;self.db=store.db;self.ctx=store.ctx

    def list(self,site_id,query=None):
        site=self.store.site(site_id)
        # Past rollouts: everything created since From, or the 30 most recent.
        since=None
        if (query or {}).get('from'):
            from zoneinfo import ZoneInfo
            from .store import local_range
            since=local_range({'from':query['from']},ZoneInfo(site['timezone']))[0]
        releases=self.db.rows("SELECT ReleaseId AS id,Label AS label,PDecisionVersion AS pdecision_version,PokerControllerVersion AS poker_controller_version,PublishedUtc AS published,BootstrapUrl AS bootstrap_url FROM scheduler.UpdateRelease WHERE Enabled=1 ORDER BY PublishedUtc DESC")
        machines=self.db.rows("""SELECT a.MachineId AS id,COALESCE(x.HostName,m.Description) AS name,
            g.LastHeartbeatUtc AS agent_heartbeat,g.CurrentReleaseId AS installed_release,v.Label AS installed_label,g.AgentVersion AS agent_version,g.AppsHealthy AS apps_healthy,g.Stage AS stage,
            a.LastHeartbeatUtc AS worker_heartbeat,a.IsReady AS worker_ready,
            g.LogCollectorVersion AS log_collector_version,g.LogCollectorHeartbeatUtc AS log_collector_heartbeat
            FROM scheduler.MachineAssignment a JOIN dbo.CustomerMachine m ON m.MachineId=a.MachineId
            LEFT JOIN backoffice.MachineMetadata x ON x.MachineId=a.MachineId
            LEFT JOIN scheduler.MachineUpdateAgent g ON g.MachineId=a.MachineId AND g.Enabled=1
            LEFT JOIN scheduler.UpdateRelease v ON v.ReleaseId=g.CurrentReleaseId
            WHERE a.SiteId=%s AND m.CustomerId=%s AND m.IsActive=1 ORDER BY a.MachineId""",site_id,self.ctx.customer_id)
        now=datetime.now(timezone.utc).replace(tzinfo=None)
        for machine in machines:machine['agent_online']=bool(machine['agent_heartbeat'] and machine['agent_heartbeat']>=now-timedelta(seconds=60))
        rollouts=self.db.rows("""SELECT TOP(%s) r.RolloutId AS id,r.Status AS status,r.NotBeforeUtc AS scheduled,r.CreatedUtc AS created,r.Immediate AS immediate,v.Label AS release_label
            FROM scheduler.UpdateRollout r JOIN scheduler.UpdateRelease v ON v.ReleaseId=r.ReleaseId
            WHERE r.SiteId=%s AND r.CustomerId=%s AND (%s IS NULL OR r.CreatedUtc>=%s) ORDER BY r.CreatedUtc DESC""",
            500 if since else 30,site_id,self.ctx.customer_id,since,since)
        tasks=self.db.rows("""SELECT t.TaskId AS id,t.RolloutId AS rollout_id,t.MachineId AS machine_id,
            COALESCE(x.HostName,m.Description) AS machine,t.Position AS position,t.Status AS status,t.Detail AS detail,
            t.OriginalEntries AS original_entries,t.RecoveryTarget AS recovery_target,t.StartedUtc AS started,t.CompletedUtc AS completed,t.Staged AS staged
            FROM scheduler.MachineUpdateTask t JOIN scheduler.UpdateRollout r ON r.RolloutId=t.RolloutId
            JOIN dbo.CustomerMachine m ON m.MachineId=t.MachineId LEFT JOIN backoffice.MachineMetadata x ON x.MachineId=t.MachineId
            WHERE r.SiteId=%s AND r.CustomerId=%s ORDER BY r.CreatedUtc DESC,t.Position""",site_id,self.ctx.customer_id)
        for r in rollouts:r['tasks']=[t for t in tasks if t['rollout_id']==r['id']]
        return {'releases':releases,'machines':machines,'rollouts':rollouts,'setup_url':__import__('os').environ.get('BACKOFFICE_SETUP_URL'),'setup_admin':bool(self.db.one('SELECT Subject FROM backoffice.SetupAdministrator WHERE Provider=%s AND Subject=%s',self.ctx.provider,self.ctx.subject))}

    def enroll(self,site_id,body):
        operator(self.store,site_id)
        mid=integer(body.get('machine_id'),1,field='machine')
        row=self.db.one("""SELECT a.MachineId,m.MacAddress FROM scheduler.MachineAssignment a JOIN dbo.CustomerMachine m ON m.MachineId=a.MachineId
            WHERE a.SiteId=%s AND a.MachineId=%s AND m.CustomerId=%s AND m.IsActive=1""",site_id,mid,self.ctx.customer_id)
        if not row:raise Error(404,'Machine not found')
        if self.db.one("SELECT TaskId FROM scheduler.MachineUpdateTask WHERE MachineId=%s AND StartedUtc IS NOT NULL AND CompletedUtc IS NULL",mid):raise Error(409,'Finish the current machine update before replacing its enrollment')
        keys=self.db.rows('SELECT DISTINCT PublicKey FROM scheduler.UpdateRelease WHERE Enabled=1')
        if not keys:raise Error(409,'Publish a signed release before enrolling a machine')
        token=secrets.token_urlsafe(48);digest=hashlib.sha256(token.encode()).hexdigest()
        self.db.execute("""UPDATE scheduler.MachineUpdateAgent SET TokenHash=%s,SiteId=%s,InstanceId=NULL,LastHeartbeatUtc=NULL,Enabled=1 WHERE MachineId=%s;
            IF @@ROWCOUNT=0 INSERT scheduler.MachineUpdateAgent(MachineId,SiteId,TokenHash) VALUES(%s,%s,%s)""",digest,site_id,mid,mid,site_id,digest)
        self.store.audit('updates.enroll',mid,{})
        return {'BaseUrl':PUBLIC_URL,'MachineId':mid,'SiteId':site_id,'Token':token,'TrustedKeys':[k['PublicKey'] for k in keys],
                'ExpectedMac':row['MacAddress'],'Root':r'C:\PokerSuite\Managed','DecisionHealthUrl':'http://127.0.0.1:5005/api/health'}

    def create(self,site_id,body):
        site=operator(self.store,site_id);release=guid(body.get('release_id'),'release')
        if not self.db.one('SELECT ReleaseId FROM scheduler.UpdateRelease WHERE ReleaseId=%s AND Enabled=1',release):raise Error(404,'Release not found')
        raw=body.get('machines')
        if not isinstance(raw,list) or not raw or len(raw)>100:raise Error(400,'Select between 1 and 100 machines')
        machines=[integer(m,1,field='machine') for m in raw]
        if len(set(machines))!=len(machines):raise Error(400,'A machine may appear only once')
        now=datetime.now(timezone.utc).replace(tzinfo=None)
        scheduled=now
        if body.get('start_local'):
            try:
                local=datetime.fromisoformat(body['start_local'])
                if local.tzinfo is not None:raise ValueError()
                zone=ZoneInfo(site['timezone']);aware=local.replace(tzinfo=zone)
                scheduled=aware.astimezone(timezone.utc).replace(tzinfo=None)
                if aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)!=local:raise ValueError()
            except (ValueError,TypeError):raise Error(400,'Invalid local start time')
        immediate=bool(body.get('immediate'))
        rid=str(uuid.uuid4())
        for mid in machines:
            eligible=self.db.one("""SELECT g.MachineId FROM scheduler.MachineUpdateAgent g
                JOIN scheduler.MachineAssignment a ON a.MachineId=g.MachineId AND a.SiteId=g.SiteId
                JOIN dbo.CustomerMachine m ON m.MachineId=a.MachineId
                WHERE g.MachineId=%s AND g.SiteId=%s AND m.CustomerId=%s AND m.IsActive=1 AND g.Enabled=1
                    AND g.LastHeartbeatUtc>=DATEADD(second,-60,SYSUTCDATETIME())""",mid,site_id,self.ctx.customer_id)
            if not eligible:raise Error(409,f'Machine {mid} needs a connected updater agent')
        self.db.execute("INSERT scheduler.UpdateRollout(RolloutId,CustomerId,SiteId,ReleaseId,Status,NotBeforeUtc,RequestedBy,Immediate) VALUES(%s,%s,%s,%s,'queued',%s,%s,%s)",rid,self.ctx.customer_id,site_id,release,scheduled,self.ctx.subject,immediate)
        for position,mid in enumerate(machines):self.db.execute("INSERT scheduler.MachineUpdateTask(TaskId,RolloutId,SiteId,MachineId,Position,Status) VALUES(%s,%s,%s,%s,%s,'queued')",str(uuid.uuid4()),rid,site_id,mid,position)
        self.store.audit('updates.create',rid,{'release_id':release,'machines':machines,'immediate':immediate})
        return {'id':rid}

    def control(self,site_id,rid,body):
        operator(self.store,site_id);rid=guid(rid,'rollout')
        row=self.db.one('SELECT Status FROM scheduler.UpdateRollout WITH(UPDLOCK,HOLDLOCK) WHERE RolloutId=%s AND SiteId=%s AND CustomerId=%s',rid,site_id,self.ctx.customer_id)
        if not row:raise Error(404,'Rollout not found')
        if row['Status'] in ('completed','cancelled'):raise Error(409,'This rollout has already ended')
        action=body.get('action')
        if action=='pause' and row['Status'] in ('queued','running'):
            if self.db.one("SELECT TaskId FROM scheduler.MachineUpdateTask WHERE RolloutId=%s AND Status IN ('forcing','reconciling','stopping','installing','verifying')",rid):raise Error(409,'The active installation must finish or roll back before pausing')
            self.db.execute("UPDATE scheduler.UpdateRollout SET Status='paused',UpdatedUtc=SYSUTCDATETIME() WHERE RolloutId=%s",rid)
        elif action=='resume' and row['Status']=='paused':
            if self.db.one("SELECT TaskId FROM scheduler.MachineUpdateTask WHERE RolloutId=%s AND Status IN ('failed','rolled_back')",rid):raise Error(409,'This rollout has a failed machine. Cancel it and create a new rollout after reviewing the failure.')
            self.db.execute("UPDATE scheduler.UpdateRollout SET Status='running',UpdatedUtc=SYSUTCDATETIME() WHERE RolloutId=%s",rid)
            self.db.execute('UPDATE scheduler.MachineUpdateTask SET UpdatedUtc=SYSUTCDATETIME() WHERE RolloutId=%s AND CompletedUtc IS NULL AND StartedUtc IS NOT NULL',rid)
        elif action=='cancel':
            if self.db.one("SELECT TaskId FROM scheduler.MachineUpdateTask WHERE RolloutId=%s AND Status IN ('forcing','reconciling','stopping','installing','verifying')",rid):raise Error(409,'Wait for the active installation to finish before cancelling')
            self.db.execute("UPDATE scheduler.MachineAssignment SET MaintenanceTaskId=NULL WHERE MaintenanceTaskId IN(SELECT TaskId FROM scheduler.MachineUpdateTask WHERE RolloutId=%s)",rid)
            self.db.execute("UPDATE scheduler.MachineUpdateTask SET Status='cancelled',CompletedUtc=SYSUTCDATETIME(),UpdatedUtc=SYSUTCDATETIME() WHERE RolloutId=%s AND Status NOT IN ('completed','failed','rolled_back')",rid)
            self.db.execute("UPDATE scheduler.UpdateRollout SET Status='cancelled',UpdatedUtc=SYSUTCDATETIME() WHERE RolloutId=%s",rid)
        else:raise Error(409,'This action is not available for the current rollout state')
        self.store.audit('updates.'+action,rid,{})
        return {'accepted':True}


def machine_status(db,machine_id,headers,*,verified_device=False):
    token=headers.get('x-updater-token','')
    row=db.one("""SELECT g.TokenHash,g.SiteId,g.LastHeartbeatUtc,g.AppsHealthy,g.Stage,g.Detail,g.AgentVersion,
        v.Label AS InstalledLabel,v.PDecisionVersion,v.PokerControllerVersion,
        a.IsReady,a.LastHeartbeatUtc AS WorkerHeartbeat,m.MacAddress
        FROM scheduler.MachineUpdateAgent g JOIN dbo.CustomerMachine m ON m.MachineId=g.MachineId
        JOIN dbo.Customer c ON c.CustomerId=m.CustomerId
        JOIN scheduler.MachineAssignment a ON a.MachineId=g.MachineId AND a.SiteId=g.SiteId
        LEFT JOIN scheduler.UpdateRelease v ON v.ReleaseId=g.CurrentReleaseId
        WHERE g.MachineId=%s AND g.Enabled=1 AND m.IsActive=1 AND c.IsActive=1""",machine_id)
    if not row or (not verified_device and (len(token)<40 or len(token)>200 or not hmac.compare_digest(row['TokenHash'],hashlib.sha256(token.encode()).hexdigest()))):raise Error(401,'Invalid updater credentials')
    task=db.one("""SELECT TOP(1) t.Status AS status,t.Detail AS detail,r.Status AS rollout_status,v.Label AS release_label
        FROM scheduler.MachineUpdateTask t JOIN scheduler.UpdateRollout r ON r.RolloutId=t.RolloutId
        JOIN scheduler.UpdateRelease v ON v.ReleaseId=r.ReleaseId WHERE t.MachineId=%s AND t.SiteId=%s
        ORDER BY r.CreatedUtc DESC,t.Position""",machine_id,row['SiteId'])
    stamp=datetime.now(timezone.utc).replace(tzinfo=None)
    return {'authenticated':True,'machine_id':machine_id,'site_id':row['SiteId'],'mac':row['MacAddress'],
        'agent_online':bool(row['LastHeartbeatUtc'] and row['LastHeartbeatUtc']>=stamp-timedelta(seconds=60)),
        'agent_version':row['AgentVersion'],'agent_heartbeat':row['LastHeartbeatUtc'],'apps_healthy':bool(row['AppsHealthy']),
        'worker_ready':bool(row['IsReady']),'worker_heartbeat':row['WorkerHeartbeat'],
        'installed_release':row['InstalledLabel'],'pdecision_version':row['PDecisionVersion'],
        'controller_version':row['PokerControllerVersion'],'update':task}


def agent_request(db,machine_id,headers,body,action):
    if action in ('logs-poll','logs-report'):
        from .machine_logs import collector_request
        return collector_request(db,machine_id,headers,body,action)
    if action=='status':return machine_status(db,machine_id,headers)
    token=headers.get('x-updater-token','')
    if len(token)<40 or len(token)>200:raise Error(401,'Invalid updater credentials')
    row=db.one('SELECT * FROM scheduler.MachineUpdateAgent WITH(UPDLOCK,HOLDLOCK) WHERE MachineId=%s AND Enabled=1',machine_id)
    if not row or not hmac.compare_digest(row['TokenHash'],hashlib.sha256(token.encode()).hexdigest()):raise Error(401,'Invalid updater credentials')
    instance=guid(body.get('instance_id'),'agent instance')
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    if row['InstanceId'] and str(row['InstanceId']).lower()!=instance and row['LastHeartbeatUtc'] and row['LastHeartbeatUtc']>now-timedelta(seconds=60):raise Error(409,'Another updater instance is active on this machine')
    db.execute('UPDATE scheduler.MachineUpdateAgent SET InstanceId=%s,LastHeartbeatUtc=%s,AgentVersion=%s WHERE MachineId=%s',instance,now,str(body.get('agent_version',''))[:100],machine_id)
    if action=='poll':db.execute('UPDATE scheduler.MachineUpdateAgent SET AppsHealthy=%s WHERE MachineId=%s',body.get('apps_running') is True,machine_id)
    if action=='poll' and body.get('needs_install') is True and not row['CurrentReleaseId']:
        db.execute("UPDATE scheduler.MachineUpdateAgent SET Stage='awaiting_install' WHERE MachineId=%s AND Stage IS NULL OR MachineId=%s AND Stage IN ('awaiting_install','failed')",machine_id,machine_id)
    task=db.one("""SELECT t.*,r.Status AS RolloutStatus,r.ReleaseId,r.Immediate,v.ManifestJson,v.Signature,v.ArtifactUrl,v.PDecisionVersion,v.PokerControllerVersion
        FROM scheduler.MachineUpdateTask t JOIN scheduler.UpdateRollout r ON r.RolloutId=t.RolloutId
        JOIN scheduler.UpdateRelease v ON v.ReleaseId=r.ReleaseId
        WHERE t.MachineId=%s AND t.SiteId=%s AND t.StartedUtc IS NOT NULL AND t.CompletedUtc IS NULL""",machine_id,row['SiteId'])
    if action=='report':
        if not task or guid(body.get('task_id'),'task')!=str(task['TaskId']).lower():raise Error(409,'No matching active update task')
        phase=body.get('phase');status=task['Status']
        # A pause prevents new installations; an installation already in progress
        # is allowed to finish or roll back, so the machine is not left stopped.
        if phase=='reconciling' and status=='reconciling':
            from schedule_controller.update_rollouts import unconfirmed_absence
            if task['RolloutStatus']=='paused' or not unconfirmed_absence(db,machine_id,'%s'):raise Error(409,'Fresh seat snapshots do not confirm absence')
        elif phase=='reconciled' and status=='reconciling':
            from schedule_controller.update_rollouts import unconfirmed_absence
            worker=db.one('SELECT MAX(CONVERT(int,IsReady)) AS IsReady FROM scheduler.MachineAssignment WHERE MachineId=%s',machine_id)
            if worker['IsReady'] or not unconfirmed_absence(db,machine_id,'%s'):raise Error(409,'Stop the drained worker and verify current seat snapshots before reconciliation')
            db.execute("UPDATE scheduler.Entry SET IsOpen=0,Status='closed',ClosedUtc=SYSUTCDATETIME() WHERE MachineId=%s AND IsOpen=1 AND Status='uncertain'",machine_id)
            db.execute("UPDATE scheduler.AccountSession SET IsOpen=0,ActualEndUtc=CASE WHEN StartedUtc>SYSUTCDATETIME() THEN StartedUtc ELSE SYSUTCDATETIME() END,EndReason='software_update' WHERE MachineId=%s AND IsOpen=1",machine_id)
            db.execute("UPDATE scheduler.Command SET Status='expired',IsOpen=0,ResultCode='reconciled_absent',UpdatedUtc=SYSUTCDATETIME() WHERE MachineId=%s AND IsOpen=1",machine_id)
            db.execute('DELETE scheduler.AccountLease WHERE MachineId=%s AND NOT EXISTS(SELECT 1 FROM scheduler.Entry e WHERE e.BotAccountId=AccountLease.BotAccountId AND e.IsOpen=1)',machine_id)
            db.execute("UPDATE scheduler.MachineUpdateTask SET Status='stopping',UpdatedUtc=%s,Detail='Unconfirmed entries reconciled after verified absence. Installing.' WHERE TaskId=%s",now,task['TaskId'])
        elif phase=='staged' and status in ('preparing','draining','forcing'):
            db.execute('UPDATE scheduler.MachineUpdateTask SET Staged=1 WHERE TaskId=%s',task['TaskId'])
        elif phase=='force_stopped' and status=='forcing':
            # The operator chose Immediate: open entries/sessions were cut off, not confirmed absent from
            # the table, so this is recorded as a forced interruption rather than reusing the 'software_update'/
            # 'reconciled_absent' reasons that mean a fresh seat snapshot proved the bot had actually left.
            # Tournament registrations (TableId 'T...') stay open: EvenBet keeps them through the restart and the
            # new worker resumes them, or closes those EvenBet no longer holds. Ring seats are cut off.
            db.execute("UPDATE scheduler.Entry SET IsOpen=0,Status='closed',ClosedUtc=SYSUTCDATETIME() WHERE MachineId=%s AND IsOpen=1 AND TableId NOT LIKE 'T%%'",machine_id)
            db.execute("UPDATE scheduler.Entry SET Status='uncertain' WHERE MachineId=%s AND IsOpen=1",machine_id)
            db.execute("UPDATE scheduler.AccountSession SET IsOpen=0,ActualEndUtc=SYSUTCDATETIME(),EndReason='forced_update' WHERE MachineId=%s AND IsOpen=1",machine_id)
            db.execute("UPDATE scheduler.Command SET Status='expired',IsOpen=0,ResultCode='forced_update',UpdatedUtc=SYSUTCDATETIME() WHERE MachineId=%s AND IsOpen=1",machine_id)
            db.execute('DELETE scheduler.AccountLease WHERE MachineId=%s AND NOT EXISTS(SELECT 1 FROM scheduler.Entry e WHERE e.BotAccountId=AccountLease.BotAccountId AND e.IsOpen=1)',machine_id)
            # A killed worker never marks itself stopped; its fresh heartbeat would make the new worker
            # refuse to start ('Machine has a live worker') for 90 seconds and fail the update.
            db.execute('UPDATE scheduler.MachineAssignment SET IsReady=0 WHERE MachineId=%s',machine_id)
            db.execute("UPDATE scheduler.MachineUpdateTask SET Status='stopping',UpdatedUtc=%s,Detail='Applications were force-stopped immediately; open sessions were cut off, not confirmed absent from the table.' WHERE TaskId=%s",now,task['TaskId'])
        elif phase=='installing' and status in ('stopping','installing'):
            if task['RolloutStatus']=='paused':raise Error(409,'Rollout is paused')
            # Only an immediate update (force_stopped) reaches this with open entries: its kept tournament registrations.
            if db.one("SELECT TOP(1) EntryId FROM scheduler.Entry WHERE MachineId=%s AND IsOpen=1 AND TableId NOT LIKE 'T%%'",machine_id):raise Error(409,'The machine still has open table entries')
            if db.one('SELECT TOP(1) SessionId FROM scheduler.AccountSession WHERE MachineId=%s AND IsOpen=1',machine_id):raise Error(409,'The machine still has open sessions')
            db.execute("UPDATE scheduler.MachineUpdateTask SET Status='installing',UpdatedUtc=%s,Detail='Restarting applications.' WHERE TaskId=%s",now,task['TaskId'])
        elif phase=='verifying' and status in ('installing','verifying'):
            db.execute("UPDATE scheduler.MachineUpdateTask SET Status='verifying',UpdatedUtc=%s,Detail='Checking application startup and health.' WHERE TaskId=%s",now,task['TaskId'])
        elif phase=='resuming' and status in ('verifying','resuming'):
            if str(body.get('pdecision_version'))!=task['PDecisionVersion'] or str(body.get('controller_version'))!=task['PokerControllerVersion']:raise Error(409,'Installed versions do not match the release')
            worker=db.one('SELECT IsReady,LastHeartbeatUtc FROM scheduler.MachineAssignment WHERE SiteId=%s AND MachineId=%s',task['SiteId'],machine_id)
            if not worker or not worker['IsReady'] or not worker['LastHeartbeatUtc'] or worker['LastHeartbeatUtc']<now-timedelta(seconds=60):raise Error(409,'Waiting for the updated controller heartbeat')
            db.execute('UPDATE scheduler.MachineUpdateAgent SET CurrentReleaseId=%s WHERE MachineId=%s',task['ReleaseId'],machine_id)
            db.execute('UPDATE scheduler.MachineAssignment SET MaintenanceTaskId=NULL WHERE MachineId=%s',machine_id)
            if status!='resuming':db.execute("UPDATE scheduler.MachineUpdateTask SET Status='resuming',UpdatedUtc=%s,Detail='Healthy. Restoring scheduled traffic.' WHERE TaskId=%s",now,task['TaskId'])
        elif phase in ('failed','rolled_back'):
            db.execute('UPDATE scheduler.MachineUpdateTask SET Status=%s,CompletedUtc=%s,UpdatedUtc=%s,Detail=%s WHERE TaskId=%s',phase,now,now,str(body.get('detail','Update failed'))[:1000],task['TaskId'])
            db.execute("UPDATE scheduler.UpdateRollout SET Status='paused',UpdatedUtc=%s WHERE RolloutId=%s",now,task['RolloutId'])
            # Only a verified rollback may restore traffic. An unverified failed
            # installation remains in maintenance for explicit intervention.
            if phase=='rolled_back':db.execute('UPDATE scheduler.MachineAssignment SET MaintenanceTaskId=NULL WHERE MachineId=%s',machine_id)
        else:raise Error(409,'Invalid updater state transition')
        db.execute('UPDATE scheduler.MachineUpdateAgent SET Stage=%s,Detail=%s WHERE MachineId=%s',str(phase)[:100],str(body.get('detail',''))[:1000],machine_id)
        return {'accepted':True}
    if action!='poll':raise Error(404,'Updater endpoint not found')
    return {'installed_release_id':str(row['CurrentReleaseId']) if row['CurrentReleaseId'] else None,'task':None if not task else {'id':str(task['TaskId']),'status':task['Status'],'paused':task['RolloutStatus']=='paused',
        'release_id':str(task['ReleaseId']),'manifest':task['ManifestJson'],'signature':task['Signature'],'url':task['ArtifactUrl'],'immediate':bool(task['Immediate'])}}
