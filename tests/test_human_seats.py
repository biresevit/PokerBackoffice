from datetime import datetime, timedelta, timezone

from backoffice.human_seats import current, history


def test_history_keeps_missing_and_incomplete_samples_unknown_and_scopes_machine():
    start = datetime(2026, 11, 24, 10, 15, tzinfo=timezone.utc)
    class Db:
        def rows(self, sql, *args):
            assert 'MachineId=%s' in sql and args[2:4] == (1006, 5)
            assert args[4:6] == (start.replace(tzinfo=None), (start+timedelta(hours=3)).replace(tzinfo=None))
            return [dict(at=start.replace(minute=0, tzinfo=None), humans=0, minimum=0, maximum=0,
                         known_samples=12, samples=20, fresh_tables=0, total_tables=2),
                    dict(at=start.replace(hour=11, minute=0, tzinfo=None), humans=None,
                         minimum=None, maximum=None, known_samples=0, samples=60)]
    result = history(Db(), 1006, start, start+timedelta(hours=3), machine=5)
    assert result['scope'] == 'pc_bot_tables'
    assert [p['humans'] for p in result['points']] == [0, None, None, None]
    assert result['points'][0]['known_samples'] == 12
    assert result['points'][1]['samples'] == 60
    assert result['points'][2]['samples'] == 0


def test_current_unknown_is_not_replaced_by_observed_lower_bound():
    class Db:
        def rows(self, sql, *args):
            assert args == (1,) and 'DATEADD(second,-180' in sql
            return [dict(at=datetime(2026, 11, 24), humans=None, observed_humans=4,
                         fresh_tables=1, total_tables=2)]
    assert current(Db(), 1)['humans'] is None
    class Empty:
        def rows(self, *args): return []
    assert current(Empty(), 1) is None


def test_minute_averages_and_no_future_fill():
    class Db:
        def rows(self, *args):
            return [dict(at=datetime(2026,11,24,10), humans=2.25, minimum=2, maximum=3,
                         known_samples=1, samples=1)]
    start = datetime(2026,11,24,10,tzinfo=timezone.utc)
    data = history(Db(), 1, start, start+timedelta(minutes=2), 1)
    assert [p['humans'] for p in data['points']] == [2.2, None]


def test_partial_table_coverage_is_explicit():
    class Db:
        def rows(self, *args):
            return [dict(at=datetime(2026,11,24,10),humans=8,minimum=7,maximum=9,
                         known_samples=10,complete_samples=0,samples=20)]
    start=datetime(2026,11,24,10,tzinfo=timezone.utc)
    point=history(Db(),1,start,start+timedelta(hours=1))['points'][0]
    assert point['partial'] is True and point['humans']==8
