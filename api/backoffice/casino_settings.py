"""Decision settings keyed by the authorized customer and registered poker site."""
import hashlib
import json

from .validation import Error, choice


def version(row):
    return hashlib.sha256(json.dumps(row,sort_keys=True,default=str).encode()).hexdigest()


class CasinoSettings:
    def __init__(self,store):self.store=store;self.db=store.db

    def row(self,casino,lock=False):
        hint='WITH(UPDLOCK,HOLDLOCK)' if lock else ''
        return self.db.one(f'''SELECT UseHelp AS use_help,ProfileVsHumans AS profile_vs_humans,
            ProfileMaxStake AS profile_max_stake,ProfileInTournaments AS profile_in_tournaments,
            UpdatedUtc AS updated FROM dbo.CasinoSettings {hint} WHERE Casino=%s AND CustomerId=%s''',casino,self.store.ctx.customer_id)

    def get(self,site_id):
        site=self.store.site(site_id);row=self.row(site['name'])
        defaults={'use_help':False,'profile_vs_humans':'Everyone','profile_max_stake':None,'profile_in_tournaments':True}
        return {'casino':site['name'],'exists':row is not None,'settings':row or defaults,
                'version':version(row),'editable':self.store.ctx.role=='operator','customer_id':self.store.ctx.customer_id,'refresh_minutes':10}

    def save(self,site_id,body):
        site=self.store.site(site_id)
        if self.store.ctx.role!='operator':raise Error(403,'Your account has view-only access')
        allowed={'version','use_help','profile_vs_humans','profile_max_stake','profile_in_tournaments'}
        if set(body)-allowed:raise Error(400,'Unknown casino setting')
        for key in ('use_help','profile_in_tournaments'):
            if type(body.get(key)) is not bool:raise Error(400,'Choose on or off for '+key.replace('_',' '))
        humans=choice(body.get('profile_vs_humans'),('Everyone','WeakHumans','Never'),'profile strategy against humans')
        stake=body.get('profile_max_stake')
        if stake is not None:choice(stake,('Micro','Low','Mid','High'),'maximum profile stake')
        row=self.row(site['name'],lock=True)
        if body.get('version')!=version(row):raise Error(409,'Casino settings changed since this page was loaded. Reload before saving.')
        values=(body['use_help'],humans,stake,body['profile_in_tournaments'],site['name'],self.store.ctx.customer_id)
        if row:
            self.db.execute('''UPDATE dbo.CasinoSettings SET UseHelp=%s,ProfileVsHumans=%s,
                ProfileMaxStake=%s,ProfileInTournaments=%s,UpdatedUtc=SYSUTCDATETIME() WHERE Casino=%s AND CustomerId=%s''',*values)
        else:
            self.db.execute('''INSERT dbo.CasinoSettings(UseHelp,ProfileVsHumans,ProfileMaxStake,ProfileInTournaments,Casino,CustomerId)
                VALUES(%s,%s,%s,%s,%s,%s)''',*values)
        self.store.audit('casino.settings.save',site_id,{'casino':site['name'],'before':row,'after':{k:body.get(k) for k in allowed if k!='version'}})
        return self.get(site_id)
