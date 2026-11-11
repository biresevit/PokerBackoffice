"""Decision settings keyed by the authorized customer and registered poker site."""
import hashlib
import json
from decimal import Decimal

from .validation import Error, choice, number

FEATURES = {'help_players': 'CardSharing', 'profile_players': 'Profile'}
MAX_PLAYERS = 500
DEFAULTS = {'use_help': False, 'help_min_big_blind': None, 'help_vs_humans': 'Everyone',
            'profile_vs_humans': 'Everyone', 'profile_max_stake': None, 'profile_min_big_blind': None,
            'profile_in_tournaments': True}


def version(row, players):
    # the player lists are part of the version, so a stale page can't overwrite a list someone else changed
    return hashlib.sha256(json.dumps([row, players], sort_keys=True, default=str).encode()).hexdigest()


def plain(value):
    return float(value) if isinstance(value, Decimal) else value


def min_big_blind(value, field):
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
        return self.db.one(f'''SELECT UseHelp AS use_help,HelpMinBigBlind AS help_min_big_blind,HelpVsHumans AS help_vs_humans,
            ProfileVsHumans AS profile_vs_humans,ProfileMaxStake AS profile_max_stake,ProfileMinBigBlind AS profile_min_big_blind,
            ProfileInTournaments AS profile_in_tournaments,
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
        for key in ('use_help', 'profile_in_tournaments'):
            if type(body.get(key)) is not bool: raise Error(400, 'Choose on or off for ' + key.replace('_', ' '))
        help_humans = choice(body.get('help_vs_humans', 'Everyone'), ('Everyone', 'ListedPlayers'), 'card sharing against humans')
        humans = choice(body.get('profile_vs_humans'), ('Everyone', 'WeakHumans', 'ListedPlayers', 'Never'), 'profile strategy against humans')
        stake = body.get('profile_max_stake')
        if stake is not None: choice(stake, ('Micro', 'Low', 'Mid', 'High'), 'maximum profile stake')
        help_min = min_big_blind(body.get('help_min_big_blind'), 'card sharing minimum big blind')
        profile_min = min_big_blind(body.get('profile_min_big_blind'), 'profile minimum big blind')
        players = {key: player_list(body.get(key, []), label) for key, label in
                   (('help_players', 'card sharing player list'), ('profile_players', 'profile player list'))}
        if body['use_help'] and help_humans == 'ListedPlayers' and not players['help_players']:
            raise Error(400, 'Add at least one player to the card sharing list, or use card sharing in every hand')
        if humans == 'ListedPlayers' and not players['profile_players']:
            raise Error(400, 'Add at least one player to the profile list, or choose another profile option')
        row = self.row(site['name'], lock=True); before = self.players(site['name'])
        if body.get('version') != version(row, before):
            raise Error(409, 'Casino settings changed since this page was loaded. Reload before saving.')
        values = (body['use_help'], help_min, help_humans, humans, stake, profile_min, body['profile_in_tournaments'],
                  site['name'], self.store.ctx.customer_id)
        if row:
            self.db.execute('''UPDATE dbo.CasinoSettings SET UseHelp=%s,HelpMinBigBlind=%s,HelpVsHumans=%s,ProfileVsHumans=%s,
                ProfileMaxStake=%s,ProfileMinBigBlind=%s,ProfileInTournaments=%s,UpdatedUtc=SYSUTCDATETIME() WHERE Casino=%s AND CustomerId=%s''', *values)
        else:
            self.db.execute('''INSERT dbo.CasinoSettings(UseHelp,HelpMinBigBlind,HelpVsHumans,ProfileVsHumans,ProfileMaxStake,
                ProfileMinBigBlind,ProfileInTournaments,Casino,CustomerId) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)''', *values)
        for key, feature in FEATURES.items():
            if players[key] == before[key]: continue
            self.db.execute('DELETE dbo.CasinoSettingsPlayer WHERE Casino=%s AND CustomerId=%s AND Feature=%s',
                            site['name'], self.store.ctx.customer_id, feature)
            for name in players[key]:
                self.db.execute('INSERT dbo.CasinoSettingsPlayer(CustomerId,Casino,Feature,PlayerName) VALUES(%s,%s,%s,%s)',
                                self.store.ctx.customer_id, site['name'], feature, name)
        after = {'use_help': body['use_help'], 'help_min_big_blind': help_min, 'help_vs_humans': help_humans,
                 'profile_vs_humans': humans, 'profile_max_stake': stake, 'profile_min_big_blind': profile_min,
                 'profile_in_tournaments': body['profile_in_tournaments'], **players}
        self.store.audit('casino.settings.save', site_id, {'casino': site['name'], 'before': {**(row or {}), **before}, 'after': after})
        return self.get(site_id)
