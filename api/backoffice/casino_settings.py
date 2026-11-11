"""Decision settings keyed by the authorized customer and registered poker site.

Card sharing and the solver strategy against humans are each switched on or off. When on, a feature is used in ring
games from a minimum big blind, in SNG/MTT from a minimum buy-in (empty: every stake) and, whatever the game or
stake, in every hand with one of its listed players.
"""
import hashlib
import json
from decimal import Decimal

from .validation import Error, number

FEATURES = {'help_players': 'CardSharing', 'solver_players': 'Solver'}
MAX_PLAYERS = 500
SWITCHES = ('use_help', 'solver_vs_humans')
MINIMUMS = {'help_min_big_blind': 'card sharing minimum big blind', 'help_min_buy_in': 'card sharing minimum buy-in',
            'solver_min_big_blind': 'solver minimum big blind', 'solver_min_buy_in': 'solver minimum buy-in'}
DEFAULTS = {'use_help': False, 'help_min_big_blind': None, 'help_min_buy_in': None,
            'solver_vs_humans': False, 'solver_min_big_blind': None, 'solver_min_buy_in': None}


def version(row, players):
    # the player lists are part of the version, so a stale page can't overwrite a list someone else changed
    return hashlib.sha256(json.dumps([row, players], sort_keys=True, default=str).encode()).hexdigest()


def plain(value):
    return float(value) if isinstance(value, Decimal) else value


def minimum(value, field):
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        raise Error(400, f'Invalid {field}')
    result = number(value, 0, 1000000, field)
    return None if result == 0 else result


def player_list(value, field):
    if not isinstance(value, list):
        raise Error(400, f'Invalid {field}')
    names, seen = [], set()
    for name in value:
        if not isinstance(name, str) or any(ord(c) < 32 for c in name) or len(name.strip()) > 100:
            raise Error(400, f'Player names in the {field} must contain up to 100 printable characters')
        name = name.strip()
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            names.append(name)
    if len(names) > MAX_PLAYERS:
        raise Error(400, f'The {field} can have at most {MAX_PLAYERS} players')
    return names


class CasinoSettings:
    def __init__(self, store): self.store = store; self.db = store.db

    def row(self, casino, lock=False):
        hint = 'WITH(UPDLOCK,HOLDLOCK)' if lock else ''
        return self.db.one(f'''SELECT UseHelp AS use_help,HelpMinBigBlind AS help_min_big_blind,HelpMinBuyIn AS help_min_buy_in,
            SolverVsHumans AS solver_vs_humans,SolverMinBigBlind AS solver_min_big_blind,SolverMinBuyIn AS solver_min_buy_in,
            UpdatedUtc AS updated FROM dbo.CasinoSettings {hint} WHERE Casino=%s AND CustomerId=%s''', casino, self.store.ctx.customer_id)

    def players(self, casino):
        rows = self.db.rows('''SELECT Feature AS feature,PlayerName AS name FROM dbo.CasinoSettingsPlayer
            WHERE Casino=%s AND CustomerId=%s ORDER BY Feature,PlayerName''', casino, self.store.ctx.customer_id)
        return {key: [r['name'] for r in rows if r['feature'] == feature] for key, feature in FEATURES.items()}

    def get(self, site_id):
        site = self.store.site(site_id); row = self.row(site['name']); players = self.players(site['name'])
        settings = {k: plain(v) for k, v in row.items()} if row else dict(DEFAULTS)
        return {'casino': site['name'], 'exists': row is not None, 'settings': {**settings, **players},
                'version': version(row, players), 'editable': self.store.ctx.role == 'operator',
                'customer_id': self.store.ctx.customer_id, 'refresh_minutes': 10}

    def save(self, site_id, body):
        site = self.store.site(site_id)
        if self.store.ctx.role != 'operator': raise Error(403, 'Your account has view-only access')
        allowed = {'version', *DEFAULTS, *FEATURES}
        if set(body) - allowed: raise Error(400, 'Unknown casino setting')
        for key in SWITCHES:
            if type(body.get(key)) is not bool: raise Error(400, 'Choose on or off for ' + key.replace('_', ' '))
        values = {key: minimum(body.get(key), label) for key, label in MINIMUMS.items()}
        values.update({key: body[key] for key in SWITCHES})
        players = {key: player_list(body.get(key, []), label) for key, label in
                   (('help_players', 'card sharing player list'), ('solver_players', 'solver player list'))}
        row = self.row(site['name'], lock=True); before = self.players(site['name'])
        if body.get('version') != version(row, before):
            raise Error(409, 'Casino settings changed since this page was loaded. Reload before saving.')
        # The legacy columns keep PDecision builds before 1.0.0.50 close to the new settings:
        # solver on = the strong strategy against all humans, off = profiles against everyone.
        solver = values['solver_vs_humans']
        args = (values['use_help'], values['help_min_big_blind'], values['help_min_buy_in'], solver,
                values['solver_min_big_blind'], values['solver_min_buy_in'], 'Never' if solver else 'Everyone', not solver,
                site['name'], self.store.ctx.customer_id)
        if row:
            self.db.execute('''UPDATE dbo.CasinoSettings SET UseHelp=%s,HelpMinBigBlind=%s,HelpMinBuyIn=%s,SolverVsHumans=%s,
                SolverMinBigBlind=%s,SolverMinBuyIn=%s,ProfileVsHumans=%s,ProfileInTournaments=%s,HelpVsHumans='Everyone',
                ProfileMaxStake=NULL,ProfileMinBigBlind=NULL,UpdatedUtc=SYSUTCDATETIME() WHERE Casino=%s AND CustomerId=%s''', *args)
        else:
            self.db.execute('''INSERT dbo.CasinoSettings(UseHelp,HelpMinBigBlind,HelpMinBuyIn,SolverVsHumans,SolverMinBigBlind,
                SolverMinBuyIn,ProfileVsHumans,ProfileInTournaments,Casino,CustomerId) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''', *args)
        for key, feature in FEATURES.items():
            if players[key] == before[key]: continue
            self.db.execute('DELETE dbo.CasinoSettingsPlayer WHERE Casino=%s AND CustomerId=%s AND Feature=%s',
                            site['name'], self.store.ctx.customer_id, feature)
            for name in players[key]:
                self.db.execute('INSERT dbo.CasinoSettingsPlayer(CustomerId,Casino,Feature,PlayerName) VALUES(%s,%s,%s,%s)',
                                self.store.ctx.customer_id, site['name'], feature, name)
        after = {**{k: values[k] for k in DEFAULTS}, **players}
        self.store.audit('casino.settings.save', site_id, {'casino': site['name'], 'before': {**(row or {}), **before}, 'after': after})
        return self.get(site_id)
