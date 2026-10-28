from __future__ import annotations

import os
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


@contextmanager
def session():
    connection = connect()
    try:
        yield Database(connection)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
