"""Provision schema and explicit Microsoft-identity/customer memberships."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
from backoffice.db import connect, Database


def migrate(db):
    db.execute("""IF SCHEMA_ID(N'backoffice') IS NULL EXEC(N'CREATE SCHEMA backoffice');
        IF OBJECT_ID(N'backoffice.SchemaMigration',N'U') IS NULL
        CREATE TABLE backoffice.SchemaMigration(Version nvarchar(100) PRIMARY KEY,Sha256 char(64) NOT NULL,
            AppliedUtc datetime2(3) NOT NULL DEFAULT SYSUTCDATETIME());""")
    applied = []
    for path in sorted((ROOT / "sql").glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.replace("\r\n", "\n").encode()).hexdigest()
        row = db.one("SELECT Sha256 FROM backoffice.SchemaMigration WHERE Version=%s", path.name)
        if row:
            if row["Sha256"] != checksum:
                raise RuntimeError("Applied migration was modified; add a new migration")
            continue
        for batch in re.split(r"(?im)^GO\s*$", sql):
            if batch.strip():
                db.execute(batch)
        db.execute("INSERT backoffice.SchemaMigration(Version,Sha256) VALUES(%s,%s)", path.name, checksum)
        applied.append(path.name)
    return applied


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("migrate", "requests", "grant", "revoke"))
    p.add_argument("--apply", action="store_true")
    p.add_argument("--customer", default="Nenad")
    p.add_argument("--subject", help="Exact userId returned by Microsoft via this Static Web App")
    p.add_argument("--email", help="Display label only; never used as the identity key")
    p.add_argument("--role", choices=("viewer", "operator"), default="operator")
    p.add_argument("--local-machine", type=int, help="Record this PC's hostname for the specified registered machine")
    args = p.parse_args()
    conn = connect()
    try:
        db = Database(conn)
        if args.command == "migrate":
            db.execute("""DECLARE @result int; EXEC @result=sys.sp_getapplock
                @Resource=N'PokerBackoffice:migrate',@LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=10000;
                IF @result<0 THROW 51110,'Could not lock backoffice migration',1;""")
            result = {"migrations": migrate(db)}
            if args.local_machine:
                db.execute("UPDATE backoffice.MachineMetadata SET HostName=%s WHERE MachineId=%s", socket.gethostname(), args.local_machine)
        elif args.command == "requests":
            result = db.rows("SELECT Provider,Subject,UserDetails,RequestedUtc FROM backoffice.AccessRequest ORDER BY RequestedUtc DESC")
        else:
            if not args.subject or not 1 <= len(args.subject) <= 200:
                p.error("grant/revoke requires the exact --subject from the login access request")
            customer = db.one("SELECT CustomerId FROM dbo.Customer WHERE CustomerName=%s AND IsActive=1", args.customer)
            if not customer:
                raise RuntimeError("Active customer not found")
            cid = customer["CustomerId"]
            row = db.one("SELECT Subject FROM backoffice.Membership WITH(UPDLOCK,HOLDLOCK) WHERE Provider='aad' AND Subject=%s AND CustomerId=%s", args.subject, cid)
            if args.command == "grant":
                if row:
                    db.execute("UPDATE backoffice.Membership SET IsActive=1,Role=%s,DisplayEmail=%s WHERE Provider='aad' AND Subject=%s AND CustomerId=%s", args.role, args.email, args.subject, cid)
                else:
                    db.execute("INSERT backoffice.Membership(Provider,Subject,CustomerId,DisplayEmail,Role) VALUES('aad',%s,%s,%s,%s)", args.subject, cid, args.email, args.role)
            else:
                db.execute("UPDATE backoffice.Membership SET IsActive=0 WHERE Provider='aad' AND Subject=%s AND CustomerId=%s", args.subject, cid)
            result = {"action": args.command, "customer": args.customer, "subject": args.subject, "role": args.role}
        print(json.dumps(result, default=str, indent=2))
        if args.apply:
            conn.commit()
            print("Committed")
        else:
            conn.rollback()
            print("Read-only / rolled back; use --apply to persist changes")
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
