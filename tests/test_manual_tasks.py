"""Operator-created Join/Leave tasks go through the scheduler's own Entry/Command/Outbox journal."""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backoffice.manual_tasks import ManualTasks
from backoffice.validation import Error


class Database:
    def __init__(self, tables=None, entries=None, ready=True, lease=None):
        self.writes = []
        self.session = dict(session_id='s1', id=4, username='emma', tier='high', max_tables=3, machine_id=10,
                            machine='DESKTOP-567E93', epoch='EPOCH', machine_ready=ready)
        self.entries = entries or []
        self.lobby = tables if tables is not None else [
            dict(id='t1', name='Full', game='NLH', big_blind=Decimal(2), seats=6, occupied=6),
            dict(id='t2', name='Open', game='NLH', big_blind=Decimal(2), seats=6, occupied=3),
            dict(id='t3', name='Micro', game='NLH', big_blind=Decimal('0.1'), seats=6, occupied=2)]
        self.lease = lease
        self.tournaments = []
        self.excluded = []

    def rows(self, sql, *args):
        if 'FROM scheduler.AccountSession s' in sql: return [dict(self.session)]
        if 'FROM scheduler.Entry e LEFT JOIN' in sql: return [dict(e) for e in self.entries]
        if 'FROM scheduler.StakeBand' in sql:
            return [dict(Tier='high', MinBigBlind=Decimal(1), MaxBigBlind=Decimal(4), UpperInclusive=True,
                         TournamentMinBuyIn=Decimal(10), TournamentMaxBuyIn=Decimal(50)),
                    dict(Tier='low', MinBigBlind=Decimal('.05'), MaxBigBlind=Decimal('.5'), UpperInclusive=False,
                         TournamentMinBuyIn=None, TournamentMaxBuyIn=None)]
        if "TableType IN ('SNG','MTT')" in sql: return [dict(t) for t in self.tournaments]
        if 'FROM scheduler.LobbyTable' in sql: return [dict(t) for t in self.lobby]
        raise AssertionError(sql)

    def one(self, sql, *args):
        if 'WITH(UPDLOCK,HOLDLOCK)' in sql: return None
        if 'COUNT(*) AS n' in sql: return {'n': 0}
        if 'ConfigVersion' in sql: return {'ConfigVersion': 7}
        if 'FROM scheduler.AccountLease' in sql: return self.lease
        raise AssertionError(sql)

    def execute(self, sql, *args): self.writes.append((sql, args))

    def written(self, table): return [args for sql, args in self.writes if f'INSERT scheduler.{table}' in sql]


def tasks(db, role='operator'):
    store = SimpleNamespace(db=db, ctx=SimpleNamespace(role=role, customer_id=1, subject='me'),
                            site=lambda s: {'timezone': 'UTC'}, audit=lambda *a: None,
                            excluded_tournaments=lambda s: list(db.excluded))
    return ManualTasks(store)


def test_join_goes_to_the_sessions_pc_at_a_free_table_of_the_bots_stakes():
    db = Database()
    result = tasks(db).create(1, {'kind': 'join', 'account_id': '4', 'table_id': 'any'})
    assert result['table'] == 't2' and result['machine'] == 'DESKTOP-567E93'
    entry, = db.written('Entry')
    assert entry[2:6] == (4, 10, 'EPOCH', 't2') and entry[-1] == 's1'
    command, = db.written('Command')
    assert command[3:5] == (10, 'EPOCH') and command[5] == 7
    assert len(db.written('Outbox')) == 1 and len(db.written('AccountLease')) == 1


def test_join_options_offer_only_free_tables_at_the_bots_stakes():
    session, = tasks(Database()).options(1)['sessions']
    assert session['join_tables'] == ['t2'] and 'epoch' not in session


@pytest.mark.parametrize('body,db', [
    ({'kind': 'join', 'account_id': 4, 'table_id': 't1'}, Database()),   # full
    ({'kind': 'join', 'account_id': 4, 'table_id': 't3'}, Database()),   # other stakes
    ({'kind': 'join', 'account_id': 4}, Database(ready=False)),          # PC offline
    ({'kind': 'join', 'account_id': 4}, Database(lease={'MachineId': 16, 'WorkerEpoch': 'X', 'RequiresReconciliation': False})),
    ({'kind': 'join', 'account_id': 4}, Database(entries=[dict(id=f'e{n}', account_id=4, table_id=f'x{n}', status='seated',
                                                                 table_name='x', big_blind=2, leaving=False) for n in range(3)])),
    ({'kind': 'leave', 'account_id': 4}, Database()),                    # nothing to leave
    ({'kind': 'scan', 'account_id': 4}, Database()),
])
def test_invalid_manual_tasks_write_nothing(body, db):
    with pytest.raises(Error):
        tasks(db).create(1, body)
    assert not db.writes


def test_leave_targets_a_seated_table_and_skips_one_already_leaving():
    entries = [dict(id='e1', account_id=4, table_id='t2', status='seated', table_name='Open', big_blind=2, leaving=True),
               dict(id='e2', account_id=4, table_id='t4', status='sitting_out', table_name='Other', big_blind=2, leaving=False)]
    db = Database(entries=entries)
    result = tasks(db).create(1, {'kind': 'leave', 'account_id': 4})
    assert result['table'] == 't4'
    command, = db.written('Command')
    assert command[2] == 'e2' and not db.written('Entry')


def test_viewers_cannot_create_tasks():
    db = Database()
    with pytest.raises(Error) as error:
        tasks(db, 'viewer').create(1, {'kind': 'join', 'account_id': 4})
    assert error.value.status == 403 and not db.writes


def tournament(i, fmt, buy_in, registered, minutes=None):
    from datetime import datetime, timedelta
    start = datetime(2030, 1, 1) + timedelta(minutes=minutes) if minutes is not None else None
    return dict(id=f'T{i}', name=f'{fmt} {i}', format=fmt, buy_in=Decimal(buy_in), registered=registered,
                max_players=6 if fmt == 'SNG' else 3000, start=start)


def test_register_sng_picks_the_fullest_sng_in_the_tier_buy_in_range():
    import json
    db = Database()
    db.tournaments = [tournament(1, 'SNG', 20, 2), tournament(2, 'SNG', 20, 4), tournament(3, 'SNG', 200, 5),
                      tournament(4, 'MTT', 20, 90, minutes=30)]
    result = tasks(db).create(1, {'kind': 'register_sng', 'account_id': '4', 'table_id': 'any'})
    # T3 has more players but its buy-in is outside the high tier's 10-50 range.
    assert result['table'] == 'T2' and result['kind'] == 'register_sng'
    command, = db.written('Command')
    payload = json.loads(command[6])
    assert payload['format'] == 'SNG' and payload['tournament_id'] == 2 and payload['manual'] is True


def test_register_skips_tournaments_with_an_excluded_name():
    db = Database()
    db.tournaments = [tournament(1, 'SNG', 20, 5), tournament(2, 'SNG', 20, 2)]
    db.tournaments[0]['name'] = 'Shootout SNG'
    db.excluded = ['SHOOTOUT']
    assert tasks(db).create(1, {'kind': 'register_sng', 'account_id': '4', 'table_id': 'any'})['table'] == 'T2'
    assert [t['id'] for t in tasks(db).options(1)['tournaments']] == ['T2']
    with pytest.raises(Error):
        tasks(db).create(1, {'kind': 'register_sng', 'account_id': '4', 'table_id': 'T1'})


def test_register_mtt_picks_the_earliest_start():
    db = Database()
    db.tournaments = [tournament(1, 'MTT', 20, 50, minutes=90), tournament(2, 'MTT', 20, 5, minutes=30)]
    assert tasks(db).create(1, {'kind': 'register_mtt', 'account_id': '4', 'table_id': 'any'})['table'] == 'T2'


def test_leave_ignores_tournament_entries():
    db = Database(entries=[dict(id='e1', account_id=4, table_id='T7', status='seated', table_name='SNG',
                                big_blind=None, leaving=False, table_type='SNG')])
    with pytest.raises(Error, match='no seated table'):
        tasks(db).create(1, {'kind': 'leave', 'account_id': '4', 'table_id': 'any'})


def test_unregister_targets_a_tournament_the_bot_is_waiting_for():
    import json
    waiting = dict(id='e1', account_id=4, table_id='T7', status='joining', table_name='Shootout SNG',
                   big_blind=None, leaving=False, table_type='SNG')
    playing = dict(waiting, id='e2', table_id='T8', status='seated')
    db = Database(entries=[waiting, playing])
    result = tasks(db).create(1, {'kind': 'unregister', 'account_id': '4', 'table_id': 'T7'})
    assert result['table'] == 'T7' and result['kind'] == 'unregister'
    sql, args = next((s, a) for s, a in db.writes if 'INSERT scheduler.Command' in s)
    assert "'leave'" in sql and args[2] == 'e1'
    assert json.loads(args[6]) == {'manual': True, 'unregister': True, 'format': 'SNG', 'tournament_id': 7}
    with pytest.raises(Error, match='not waiting'):
        tasks(Database(entries=[waiting, playing])).create(1, {'kind': 'unregister', 'account_id': '4', 'table_id': 'T8'})
