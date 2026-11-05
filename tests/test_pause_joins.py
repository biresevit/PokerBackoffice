"""Schedule page switch: pausing stops new joins and registrations and cancels the scheduler's queued joins."""
import pytest

from backoffice.store import Context, Store
from backoffice.validation import Error


class DB:
    def __init__(self): self.calls = []
    def one(self, sql, *args):
        self.calls.append((sql, args))
        if 'FROM scheduler.Site' in sql:
            return {'id': 1, 'name': 'BluffPoker', 'customer_id': 7, 'timezone': 'UTC', 'currency': 'EUR',
                    'version': 3, 'enabled': True, 'joins_paused': False}
        if 'CancelPausedJoins' in sql: return {'n': 2}
        raise AssertionError(sql)
    def execute(self, sql, *args): self.calls.append((sql, args))


def store(role='operator'):
    db = DB()
    return db, Store(db, Context(7, 'test', 'me', role))


def test_pausing_sets_the_flag_and_cancels_queued_scheduler_joins():
    db, s = store()
    assert s.pause_joins(1, {'paused': True}) == {'joins_paused': True, 'cancelled_joins': 2}
    sql = [c[0] for c in db.calls]
    assert any('SET JoinsPaused=%s' in q for q in sql) and any('CancelPausedJoins' in q for q in sql)


def test_resuming_cancels_nothing():
    db, s = store()
    assert s.pause_joins(1, {'paused': False}) == {'joins_paused': False, 'cancelled_joins': 0}
    assert not any('CancelPausedJoins' in c[0] for c in db.calls)


@pytest.mark.parametrize('role,body', [('viewer', {'paused': True}), ('operator', {'paused': 'yes'})])
def test_only_operators_with_a_clear_choice_can_switch(role, body):
    _, s = store(role)
    with pytest.raises(Error):
        s.pause_joins(1, body)
