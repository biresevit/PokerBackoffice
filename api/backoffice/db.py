from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager


def connect():
    """Pure Python TDS works in SWA managed Linux Functions without an ODBC install."""
    import certifi
    import pytds
    # Use individual server-side settings in Azure. Legacy local env is supported
    # only as a provisioning convenience; credentials never leave this module.
    values = {}
    for part in os.environ.get("SqlConnectionString", "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            values[k.strip().lower()] = v
    server = os.environ.get("BACKOFFICE_SQL_SERVER", values.get("server", "")).removeprefix("tcp:")
    host, _, port = server.partition(",")
    if not host:
        raise RuntimeError("Backoffice SQL server is not configured")
    return pytds.connect(server=host, port=int(port or 1433),
        database=os.environ.get("BACKOFFICE_SQL_DATABASE", values.get("initial catalog", "")),
        user=os.environ.get("BACKOFFICE_SQL_USER", values.get("user id", "")),
        password=os.environ.get("BACKOFFICE_SQL_PASSWORD", values.get("password", "")),
        cafile=certifi.where(), validate_host=True, enc_login_only=False,
        login_timeout=10, timeout=15, autocommit=False)


class Database:
    def __init__(self, connection):
        self.connection = connection

    def rows(self, sql, *params):
        with self.connection.cursor() as c:
            c.execute(sql, params)
            while c.description is None:
                if not c.nextset():
                    return []
            keys = [column[0] for column in c.description]
            return [dict(zip(keys, row)) for row in c.fetchall()]

    def one(self, sql, *params):
        rows = self.rows(sql, *params)
        return rows[0] if rows else None

    def execute(self, sql, *params):
        with self.connection.cursor() as c:
            c.execute(sql, params)
            while c.nextset():
                pass


# Idle connections reused across requests in this worker process. A new pytds connection is a
# TLS login: on the S0 database the logins of the backoffice and of the PCs' update agents were
# a large share of CPU, and each one added ~100-300 ms to the request (2026-11-11).
POOL_SIZE = 4
IDLE_PING_SECONDS = 60      # a connection idle longer than this is checked before reuse
IDLE_LIMIT_SECONDS = 240    # well below Azure SQL's 30-minute idle cut
MAX_AGE_SECONDS = 1800
_pool: list[tuple[object, float, float]] = []   # (connection, opened, last used)
_pool_lock = threading.Lock()


def _close(connection):
    try:
        connection.close()
    except Exception:
        pass


def _checkout():
    while True:
        with _pool_lock:
            item = _pool.pop() if _pool else None
        if item is None:
            return connect(), time.monotonic()
        connection, opened, used = item
        now = time.monotonic()
        if now - used > IDLE_LIMIT_SECONDS or now - opened > MAX_AGE_SECONDS:
            _close(connection)
            continue
        if now - used > IDLE_PING_SECONDS:
            try:
                with connection.cursor() as c:
                    c.execute("SELECT 1")
                    c.fetchall()
            except Exception:
                _close(connection)
                continue
        return connection, opened


def _checkin(connection, opened):
    with _pool_lock:
        if len(_pool) < POOL_SIZE:
            _pool.append((connection, opened, time.monotonic()))
            return
    _close(connection)


@contextmanager
def session():
    connection, opened = _checkout()
    try:
        yield Database(connection)
        connection.commit()
    except BaseException:
        try:
            connection.rollback()
        except Exception:
            pass
        # The session may be broken or doomed; never reuse it.
        _close(connection)
        raise
    _checkin(connection, opened)
