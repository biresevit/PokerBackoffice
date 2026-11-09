"""Operator-created Join/Leave tasks for a bot that is already in a session.

They are written exactly like the scheduler's own commands (Entry + Command + Outbox), so the
bot's PC executes them through the normal journal. The PC is always the session's PC.
"""
import json
import random
import uuid
from datetime import datetime,timedelta,timezone
from .updates import operator
from .validation import Error, is_excluded_tournament


def tournament_id(table_id):
    """Lobby key 'T…' to the platform's tournament id: a number on EvenBet, a UUID on BluffPoker."""
    raw=str(table_id).removeprefix('T')
    return int(raw) if raw.isdigit() else raw


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ManualTasks:
    def __init__(self,store):self.store=store;self.db=store.db

    def sessions(self,site_id):
        """Bots with a started, open session on a PC that is online, with their current tables."""
        rows=self.db.rows("""SELECT s.SessionId AS session_id,s.BotAccountId AS id,b.Username AS username,p.StakeTier AS tier,
            p.MaxTables AS max_tables,p.MaxSngEntries AS max_sng_entries,p.MaxMttEntries AS max_mtt_entries,s.MachineId AS machine_id,COALESCE(x.HostName,m.Description) AS machine,
            a.WorkerEpoch AS epoch,CONVERT(bit,CASE WHEN a.IsEnabled=1 AND a.IsReady=1 AND a.MaintenanceTaskId IS NULL
                AND a.WorkerEpoch IS NOT NULL AND a.LastHeartbeatUtc>=DATEADD(second,-180,SYSUTCDATETIME()) THEN 1 ELSE 0 END) AS machine_ready
            FROM scheduler.AccountSession s JOIN dbo.BotAccount b ON b.BotAccountId=s.BotAccountId
            JOIN scheduler.AccountPolicy p ON p.BotAccountId=s.BotAccountId AND p.SiteId=s.SiteId
            JOIN scheduler.MachineAssignment a ON a.MachineId=s.MachineId AND a.SiteId=s.SiteId
            JOIN dbo.CustomerMachine m ON m.MachineId=s.MachineId LEFT JOIN backoffice.MachineMetadata x ON x.MachineId=s.MachineId
            WHERE s.SiteId=%s AND s.IsOpen=1 AND s.StartedUtc<=SYSUTCDATETIME() AND m.CustomerId=%s ORDER BY b.Username""",
            site_id,self.store.ctx.customer_id)
        entries=self.db.rows("""SELECT e.EntryId AS id,e.BotAccountId AS account_id,e.TableId AS table_id,e.Status AS status,
            COALESCE(t.TableName,e.TableId) AS table_name,t.BigBlind AS big_blind,COALESCE(t.TableType,'RING') AS table_type,
            CONVERT(bit,CASE WHEN EXISTS(SELECT 1 FROM scheduler.Command c WHERE c.EntryId=e.EntryId AND c.Kind='leave' AND c.IsOpen=1) THEN 1 ELSE 0 END) AS leaving
            FROM scheduler.Entry e LEFT JOIN scheduler.LobbyTable t ON t.SiteId=e.SiteId AND t.TableId=e.TableId
            WHERE e.SiteId=%s AND e.IsOpen=1""",site_id)
        for r in rows:r['tables']=[e for e in entries if e['account_id']==r['id']]
        return rows

    def tables(self,site_id):
        """Fresh ring tables of the supported games with their stake tier."""
        bands=self.db.rows('SELECT Tier,MinBigBlind,MaxBigBlind,UpperInclusive FROM scheduler.StakeBand WHERE SiteId=%s',site_id)
        rows=self.db.rows("""SELECT TableId AS id,TableName AS name,GameType AS game,BigBlind AS big_blind,MaxSeats AS seats,
            OccupiedSeats AS occupied FROM scheduler.LobbyTable WHERE SiteId=%s AND IsOpen=1 AND TableType='RING'
            AND GameType IN ('NLH','PLO4','PLO5') AND ObservedUtc>=DATEADD(second,-60,SYSUTCDATETIME()) ORDER BY BigBlind,TableName""",site_id)
        for t in rows:
            t['tier']=next((b['Tier'] for b in bands if b['MinBigBlind']<=t['big_blind']<b['MaxBigBlind']
                            or b['UpperInclusive'] and t['big_blind']==b['MaxBigBlind']),None)
            t['reserved']=self.db.one("""SELECT COUNT(*) AS n FROM scheduler.Entry e WHERE e.SiteId=%s AND e.TableId=%s AND e.IsOpen=1
                AND e.Status IN ('reserved','joining')""",site_id,t['id'])['n']
        return rows

    def tournaments(self,site_id):
        """Open NLH tournaments seen in the last few minutes, with the stake tiers whose buy-in range fits them.
        Tournaments whose name contains one of the site's excluded names are left out."""
        ranges=self.db.rows('SELECT Tier,TournamentMinBuyIn,TournamentMaxBuyIn FROM scheduler.StakeBand WHERE SiteId=%s',site_id)
        rows=self.db.rows("""SELECT TableId AS id,TableName AS name,TableType AS format,MinBuyIn AS buy_in,
            OccupiedSeats AS registered,MaxSeats AS max_players,StartUtc AS start FROM scheduler.LobbyTable
            WHERE SiteId=%s AND TableType IN ('SNG','MTT') AND TournamentState='registering' AND GameType='NLH'
              AND ObservedUtc>=DATEADD(minute,-5,SYSUTCDATETIME())
              AND (TableType='SNG' AND OccupiedSeats<MaxSeats OR TableType='MTT' AND StartUtc>DATEADD(minute,2,SYSUTCDATETIME()))
            ORDER BY TableType,StartUtc,OccupiedSeats DESC""",site_id)
        excluded=self.store.excluded_tournaments(site_id)
        rows=[t for t in rows if not is_excluded_tournament(t['name'],excluded)]
        for t in rows:
            t['tiers']=[r['Tier'] for r in ranges if r['TournamentMinBuyIn'] is not None
                        and r['TournamentMinBuyIn']<=t['buy_in']<=r['TournamentMaxBuyIn']]
        return rows

    def options(self,site_id):
        sessions=self.sessions(site_id);tables=self.tables(site_id);tournaments=self.tournaments(site_id)
        for s in sessions:
            seated={e['table_id'] for e in s['tables']}
            s['join_tables']=[t['id'] for t in tables if t['tier']==s['tier'] and t['id'] not in seated
                              and t['occupied']+t['reserved']<t['seats']]
            s['tournaments']=[t['id'] for t in tournaments if s['tier'] in t['tiers'] and t['id'] not in seated]
            s.pop('epoch',None)
        return {'sessions':sessions,'tables':tables,'tournaments':tournaments}

    def create(self,site_id,body):
        site=operator(self.store,site_id)
        kind=str(body.get('kind') or '')
        if kind not in ('join','leave','register_sng','register_mtt','unregister'):
            raise Error(400,'Task type must be Join ring table, Leave ring table, Register SNG, Register MTT or Unregister SNG/MTT')
        try:account_id=int(body.get('account_id'))
        except (TypeError,ValueError):raise Error(400,'Choose a bot with an open session')
        # The scheduler takes this lock before it creates a join or leave for the account.
        self.db.one('SELECT BotAccountId FROM scheduler.AccountLease WITH(UPDLOCK,HOLDLOCK) WHERE BotAccountId=%s',account_id)
        session=next((s for s in self.sessions(site_id) if s['id']==account_id),None)
        if not session:raise Error(409,'That bot has no open session. Create a session first.')
        if not session['machine_ready']:raise Error(409,f"{session['machine'] or session['machine_id']} is not online and ready")
        version=self.db.one('SELECT ConfigVersion FROM scheduler.Site WHERE SiteId=%s',site_id)['ConfigVersion']
        now=utcnow();command_id=str(uuid.uuid4())
        if kind=='leave':
            # Leave applies to ring tables; a bot always plays its tournaments to the end.
            open_tables=[e for e in session['tables'] if e['status'] in ('seated','sitting_out') and not e['leaving']
                         and e.get('table_type','RING')=='RING']
            choice=str(body.get('table_id') or 'any')
            entry=random.SystemRandom().choice(open_tables) if choice=='any' and open_tables else \
                next((e for e in open_tables if e['table_id']==choice),None)
            if not entry:raise Error(409,f"{session['username']} has no seated table to leave" if choice=='any' else 'The bot is not seated at that table, or is already leaving it')
            self.db.execute("""INSERT scheduler.Command(CommandId,SiteId,EntryId,MachineId,WorkerEpoch,Kind,Status,IsOpen,
                ConfigVersion,PayloadJson,NotBeforeUtc,ExpiresUtc) VALUES(%s,%s,%s,%s,%s,'leave','pending',1,%s,%s,%s,%s)""",
                command_id,site_id,entry['id'],session['machine_id'],session['epoch'],version,json.dumps({'manual':True}),now,now+timedelta(minutes=10))
            table=entry['table_id'];table_name=entry['table_name']
        elif kind=='unregister':
            # Only before the tournament seats the bot: once it plays, it plays to the end.
            waiting=[e for e in session['tables'] if e.get('table_type') in ('SNG','MTT') and e['status']=='joining' and not e['leaving']]
            choice=str(body.get('table_id') or '')
            entry=next((e for e in waiting if e['table_id']==choice),None)
            if not entry:raise Error(409,f"{session['username']} is not waiting for that tournament to start, or an unregistration is already pending")
            self.db.execute("""INSERT scheduler.Command(CommandId,SiteId,EntryId,MachineId,WorkerEpoch,Kind,Status,IsOpen,
                ConfigVersion,PayloadJson,NotBeforeUtc,ExpiresUtc) VALUES(%s,%s,%s,%s,%s,'leave','pending',1,%s,%s,%s,%s)""",
                command_id,site_id,entry['id'],session['machine_id'],session['epoch'],version,
                json.dumps({'manual':True,'unregister':True,'format':entry['table_type'],
                            'tournament_id':tournament_id(entry['table_id'])}),now,now+timedelta(minutes=10))
            table=entry['table_id'];table_name=entry['table_name']
        elif kind in ('register_sng','register_mtt'):
            fmt='SNG' if kind=='register_sng' else 'MTT'
            if len(session['tables'])>=session['max_tables']:
                raise Error(409,f"{session['username']} already uses its maximum of {session['max_tables']} tables")
            limit=session['max_sng_entries'] if fmt=='SNG' else session['max_mtt_entries']
            held=sum(1 for e in session['tables'] if e.get('table_type')==fmt)
            if held>=limit:
                raise Error(409,f"{session['username']} already holds its maximum of {limit} {fmt} entr{'y' if limit==1 else 'ies'}; raise it on the Accounts page")
            lease=self.db.one('SELECT MachineId,WorkerEpoch,RequiresReconciliation FROM scheduler.AccountLease WHERE BotAccountId=%s',account_id)
            if lease and (lease['MachineId']!=session['machine_id'] or str(lease['WorkerEpoch']).lower()!=str(session['epoch']).lower()
                          or lease['RequiresReconciliation']):
                raise Error(409,'The bot is still being reconciled on its PC. Try again in a minute.')
            seated={e['table_id'] for e in session['tables']}
            # Manual registration may pick any open tournament; the tier's buy-in range is only a default.
            usable=[t for t in self.tournaments(site_id) if t['format']==fmt and t['id'] not in seated]
            choice=str(body.get('table_id') or 'any')
            if choice=='any':
                usable=[t for t in usable if session['tier'] in t['tiers']]
                if not usable:raise Error(409,f"No open {fmt} within the {session['tier']} tier's tournament buy-in range was seen in the last five minutes")
                # Like the scheduler: SNG with the fewest free seats (starts soonest), MTT with the earliest start.
                table_row=(min(usable,key=lambda t:(t['max_players']-t['registered'],-t['registered'])) if fmt=='SNG' else
                           min(usable,key=lambda t:(t['start'],-t['registered'])))
            else:
                table_row=next((t for t in usable if t['id']==choice),None)
                if not table_row:raise Error(409,f'That {fmt} is not open for registration, or the bot is already registered')
            if not lease:
                self.db.execute("""INSERT scheduler.AccountLease(BotAccountId,SiteId,MachineId,WorkerEpoch,LeaseToken,LeaseUntilUtc,LastConfirmedUtc)
                    VALUES(%s,%s,%s,%s,%s,DATEADD(second,90,SYSUTCDATETIME()),SYSUTCDATETIME())""",
                    account_id,site_id,session['machine_id'],session['epoch'],str(uuid.uuid4()))
            entry_id=str(uuid.uuid4());table=table_row['id'];table_name=table_row['name']
            self.db.execute("""INSERT scheduler.Entry(EntryId,SiteId,BotAccountId,MachineId,WorkerEpoch,TableId,Status,IsOpen,CreatedUtc,SessionId)
                VALUES(%s,%s,%s,%s,%s,%s,'reserved',1,SYSUTCDATETIME(),%s)""",
                entry_id,site_id,account_id,session['machine_id'],session['epoch'],table,session['session_id'])
            self.db.execute("""INSERT scheduler.Command(CommandId,SiteId,EntryId,MachineId,WorkerEpoch,Kind,Status,IsOpen,
                ConfigVersion,PayloadJson,NotBeforeUtc,ExpiresUtc) VALUES(%s,%s,%s,%s,%s,'join','pending',1,%s,%s,%s,%s)""",
                command_id,site_id,entry_id,session['machine_id'],session['epoch'],version,
                json.dumps({'account_id':account_id,'table_id':table,'manual':True,'format':fmt,
                            'tournament_id':tournament_id(table)}),now,now+timedelta(minutes=10))
        else:
            if len(session['tables'])>=session['max_tables']:
                raise Error(409,f"{session['username']} already plays its maximum of {session['max_tables']} tables")
            lease=self.db.one('SELECT MachineId,WorkerEpoch,RequiresReconciliation FROM scheduler.AccountLease WHERE BotAccountId=%s',account_id)
            if lease and (lease['MachineId']!=session['machine_id'] or str(lease['WorkerEpoch']).lower()!=str(session['epoch']).lower()
                          or lease['RequiresReconciliation']):
                raise Error(409,'The bot is still being reconciled on its PC. Try again in a minute.')
            tables={t['id']:t for t in self.tables(site_id)}
            seated={e['table_id'] for e in session['tables']}
            usable=[t for t in tables.values() if t['tier']==session['tier'] and t['id'] not in seated and t['occupied']+t['reserved']<t['seats']]
            choice=str(body.get('table_id') or 'any')
            if choice=='any':
                if not usable:raise Error(409,f"No {session['tier']}-stakes table with a free seat was observed in the last minute")
                # Like the scheduler: prefer populated tables without making the choice fixed.
                table_row=random.SystemRandom().choices(usable,weights=[(t['occupied']+1)**2 for t in usable],k=1)[0]
            else:
                table_row=next((t for t in usable if t['id']==choice),None)
                if not table_row:raise Error(409,'That table is full, not fresh, outside the bot’s stakes, or already played by the bot')
            if not lease:
                self.db.execute("""INSERT scheduler.AccountLease(BotAccountId,SiteId,MachineId,WorkerEpoch,LeaseToken,LeaseUntilUtc,LastConfirmedUtc)
                    VALUES(%s,%s,%s,%s,%s,DATEADD(second,90,SYSUTCDATETIME()),SYSUTCDATETIME())""",
                    account_id,site_id,session['machine_id'],session['epoch'],str(uuid.uuid4()))
            entry_id=str(uuid.uuid4());table=table_row['id'];table_name=table_row['name']
            self.db.execute("""INSERT scheduler.Entry(EntryId,SiteId,BotAccountId,MachineId,WorkerEpoch,TableId,Status,IsOpen,CreatedUtc,SessionId)
                VALUES(%s,%s,%s,%s,%s,%s,'reserved',1,SYSUTCDATETIME(),%s)""",
                entry_id,site_id,account_id,session['machine_id'],session['epoch'],table,session['session_id'])
            self.db.execute("""INSERT scheduler.Command(CommandId,SiteId,EntryId,MachineId,WorkerEpoch,Kind,Status,IsOpen,
                ConfigVersion,PayloadJson,NotBeforeUtc,ExpiresUtc) VALUES(%s,%s,%s,%s,%s,'join','pending',1,%s,%s,%s,%s)""",
                command_id,site_id,entry_id,session['machine_id'],session['epoch'],version,
                json.dumps({'account_id':account_id,'table_id':table,'manual':True}),now,now+timedelta(minutes=10))
        self.db.execute('INSERT scheduler.Outbox(CommandId,AvailableUtc) VALUES(%s,%s)',command_id,now)
        self.store.audit('tasks.create',command_id,{'kind':kind,'account':account_id,'table':table})
        return {'id':command_id,'kind':kind,'bot':session['username'],'table':table,'table_name':table_name,
                'machine':session['machine'] or session['machine_id']}
