"""Bulk edit of account settings and machine delete (Accounts and Machines pages, 2026-11-12)."""
import pytest

from backoffice.distributions import Distributions
from backoffice.store import Context, Store
from backoffice.validation import Error


class Db:
    def __init__(self, accounts=(), machine=None, entry=None, lease=None):
        self.accounts, self.machine, self.entry, self.lease = list(accounts), machine, entry, lease
        self.executed = []

    def rows(self, sql, *args):
        if "AccountPolicy" in sql:
            return [a for a in self.accounts if a["id"] in args[1:]]
        return []

    def one(self, sql, *args):
        if "CustomerMachine" in sql:
            return self.machine
        if "scheduler.Entry" in sql:
            return self.entry
        if "AccountLease" in sql:
            return self.lease
        return None

    def execute(self, sql, *args):
        self.executed.append((" ".join(sql.split()), args))


def store(db, role="operator"):
    s = Store(db, Context(14004, "aad", "nenad", role))
    s.site = lambda site_id, lock=False, version=None: {"id": site_id, "version": 7, "timezone": "Europe/Budapest"}
    s.bump = lambda site_id: None
    s.audits = []
    s.audit = lambda *a: s.audits.append(a)
    return s


def test_bulk_set_writes_one_validated_value_to_the_chosen_accounts_of_the_site():
    db = Db([{"id": 1, "synthetic": False}, {"id": 2, "synthetic": False}])
    result = Distributions(store(db)).bulk_set(1, {"ids": [2, 1, 2], "field": "games", "value": "NLH,PLO4,PLO5", "version": 7})
    assert result == {"version": 8, "accounts": 2, "label": "Game formats"}
    sql, args = db.executed[0]
    assert sql.startswith("UPDATE scheduler.AccountPolicy SET AllowedGames=%s") and sql.endswith("AND SiteId=%s")
    assert args == ("NLH,PLO4,PLO5", 1, 2, 1)


def test_bulk_set_profile_goes_to_the_account_and_numbers_are_range_checked():
    db = Db([{"id": 5, "synthetic": False}])
    Distributions(store(db)).bulk_set(1, {"ids": [5], "field": "strategy", "value": 5, "version": 7})
    assert db.executed[0][0].startswith("UPDATE dbo.BotAccount SET Strategy=%s") and "SiteId" not in db.executed[0][0]
    with pytest.raises(Error):
        Distributions(store(db)).bulk_set(1, {"ids": [5], "field": "max_tables", "value": 0, "version": 7})


@pytest.mark.parametrize("body,message", [
    ({"ids": [], "field": "games", "value": "NLH"}, "at least one account"),
    ({"ids": [1], "field": "Username", "value": "x"}, "Choose a setting"),
    ({"ids": [1, 99], "field": "games", "value": "NLH"}, "no longer exist"),
    ({"ids": [3], "field": "enabled", "value": True}, "Simulation-only"),
    ({"ids": [1], "field": "enabled", "value": "yes"}, "on or off"),
])
def test_bulk_set_refuses_bad_requests(body, message):
    db = Db([{"id": 1, "synthetic": False}, {"id": 3, "synthetic": True}])
    with pytest.raises(Error, match=message):
        Distributions(store(db)).bulk_set(1, {**body, "version": 7})
    assert not db.executed


def test_bulk_set_needs_operator_role():
    with pytest.raises(Error, match="view-only"):
        Distributions(store(Db([{"id": 1, "synthetic": False}]), role="viewer")).bulk_set(1, {"ids": [1], "field": "games", "value": "NLH", "version": 7})


def test_delete_machine_retires_an_idle_machine():
    db = Db(machine={"MachineId": 21, "Version": 4, "Name": "MSI"})
    s = store(db)
    assert s.delete_machine(1, 21, {"version": 4}) == {"deleted": 21}
    assert db.executed == [("EXEC backoffice.RetireMachine @CustomerId=%s,@MachineId=%s", (14004, 21))]
    assert s.audits == [("machine.delete", 21, {"name": "MSI"})]


@pytest.mark.parametrize("db,status,message", [
    (Db(), 404, "not found"),
    (Db(machine={"MachineId": 21, "Version": 5, "Name": "MSI"}), 409, "changed"),
    (Db(machine={"MachineId": 21, "Version": 4, "Name": "MSI"}, entry={"EntryId": "x"}), 409, "open tables"),
    (Db(machine={"MachineId": 21, "Version": 4, "Name": "MSI"}, lease={"BotAccountId": 7}), 409, "logged in"),
])
def test_delete_machine_refuses_unknown_changed_or_busy_machines(db, status, message):
    with pytest.raises(Error, match=message) as caught:
        store(db).delete_machine(1, 21, {"version": 4})
    assert caught.value.status == status and not db.executed


def test_delete_machine_needs_operator_role():
    with pytest.raises(Error, match="view-only"):
        store(Db(machine={"MachineId": 21, "Version": 4, "Name": "MSI"}), role="viewer").delete_machine(1, 21, {"version": 4})
