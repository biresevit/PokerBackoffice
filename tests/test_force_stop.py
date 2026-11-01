"""A force-stopped worker is marked not ready so the updated worker may start at once."""
import hashlib
from backoffice.updates import agent_request

TOKEN = 'x' * 48
TASK = '11111111-1111-1111-1111-111111111111'


class Database:
    def __init__(self): self.writes = []
    def one(self, sql, *args):
        if 'FROM scheduler.MachineUpdateAgent WITH' in sql:
            return {'TokenHash': hashlib.sha256(TOKEN.encode()).hexdigest(), 'InstanceId': None,
                    'LastHeartbeatUtc': None, 'CurrentReleaseId': 'old', 'SiteId': 1}
        if 'FROM scheduler.MachineUpdateTask t' in sql:
            return {'TaskId': TASK, 'Status': 'forcing', 'SiteId': 1, 'RolloutId': 'r', 'RolloutStatus': 'running'}
        raise AssertionError(sql)
    def execute(self, sql, *args): self.writes.append((sql, args))


def test_force_stop_report_marks_the_killed_worker_not_ready():
    db = Database()
    body = {'instance_id': '22222222-2222-2222-2222-222222222222', 'task_id': TASK, 'phase': 'force_stopped'}
    agent_request(db, 1, {'x-updater-token': TOKEN}, body, 'report')
    assert any('MachineAssignment SET IsReady=0' in sql and args == (1, 1) for sql, args in db.writes)
    assert any("Status='stopping'" in sql for sql, _ in db.writes)


def test_force_stop_keeps_tournament_registrations_open():
    # EvenBet keeps a tournament registration through the restart; the new worker resumes it or closes it.
    db = Database()
    body = {'instance_id': '22222222-2222-2222-2222-222222222222', 'task_id': TASK, 'phase': 'force_stopped'}
    agent_request(db, 1, {'x-updater-token': TOKEN}, body, 'report')
    closes = [sql for sql, _ in db.writes if 'UPDATE scheduler.Entry SET IsOpen=0' in sql]
    assert closes and all("TableId NOT LIKE 'T%%'" in sql for sql in closes)
    assert any("UPDATE scheduler.Entry SET Status='uncertain'" in sql for sql, _ in db.writes)
