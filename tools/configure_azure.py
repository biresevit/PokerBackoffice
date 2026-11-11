"""Configure the deployed API without writing credentials to disk or console."""
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"api"))
from backoffice.db import connect,Database
from azure.storage.blob import BlobServiceClient,generate_container_sas,ContainerSasPermissions

SUB="542a29f9-4770-41b9-939e-3b65068884b9"
RESOURCE=f"/subscriptions/{SUB}/resourceGroups/poker-backoffice/providers/Microsoft.Web/staticSites/poker-control-nenad"


def az(*args):
    result=subprocess.run([str(ROOT/".azure-venv/Scripts/python.exe"),"-m","azure.cli",*args,"-o","json"],capture_output=True,text=True)
    if result.returncode:
        raise RuntimeError("Azure CLI operation failed; credentials/output suppressed")
    return json.loads(result.stdout)


def arm(method,path,body=None,api_version="2024-11-01"):
    token=az("account","get-access-token","--subscription",SUB)["accessToken"]
    req=urllib.request.Request("https://management.azure.com"+path+"?api-version="+api_version,
        data=None if body is None else json.dumps(body).encode(),method=method,
        headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=90) as response:
        return json.load(response)


def main():
    settings=arm("POST",RESOURCE+"/listAppSettings",{})["properties"]
    username="poker_backoffice_app"
    password=settings.get("BACKOFFICE_SQL_PASSWORD") or secrets.token_urlsafe(36)+"aA1!"
    conn=connect()
    try:
        db=Database(conn)
        exists=db.one("SELECT name FROM sys.database_principals WHERE name=%s",username)
        if not exists:
            db.execute("CREATE USER [poker_backoffice_app] WITH PASSWORD='"+password.replace("'","''")+"'")
        elif not settings.get("BACKOFFICE_SQL_PASSWORD"):
            raise RuntimeError("Application SQL user exists without matching Azure settings; reconcile before rotation")
        permissions={
            "backoffice.ContactRateLimit":"SELECT,INSERT,UPDATE,DELETE",
            "dbo.Customer":"SELECT","dbo.CustomerMachine":"SELECT","dbo.CustomerHandHistory":"SELECT",
            "dbo.CasinoSettings":"SELECT,INSERT,UPDATE","dbo.CasinoSettingsPlayer":"SELECT,INSERT,DELETE",
            "backoffice.MachineLogRequest":"SELECT,INSERT,UPDATE",
            "reporting.HandProcessing":"SELECT","reporting.HandPlayerResult":"SELECT",
            "dbo.BotAccount":"SELECT,INSERT,UPDATE","backoffice.Membership":"SELECT",
            "backoffice.AccessRequest":"SELECT,INSERT","backoffice.AuditLog":"SELECT,INSERT",
            "backoffice.MachineMetadata":"SELECT,UPDATE","backoffice.AccountDistribution":"SELECT,INSERT,UPDATE,DELETE","backoffice.MachineAllowedSite":"SELECT,INSERT,DELETE",
            "scheduler.Site":"SELECT,UPDATE","scheduler.AccountPolicy":"SELECT,INSERT,UPDATE",
            "scheduler.ChatMessage":"SELECT","scheduler.ChatAgent":"SELECT",
            "scheduler.ChatCommand":"SELECT,INSERT","backoffice.ChatReadState":"SELECT,INSERT,UPDATE",
            "scheduler.AccountDay":"SELECT","scheduler.Entry":"SELECT,INSERT","scheduler.AccountLease":"SELECT,INSERT",
            "scheduler.AccountSession":"SELECT","scheduler.Command":"SELECT,INSERT","scheduler.Outbox":"INSERT","scheduler.MachineTelemetry":"SELECT",
            "scheduler.ScheduleWindow":"SELECT","scheduler.StakeBand":"SELECT,UPDATE",
            "scheduler.LobbyTable":"SELECT","scheduler.TableSeat":"SELECT","scheduler.MachineAssignment":"SELECT,UPDATE",
            "scheduler.LiveViewRequest":"SELECT,INSERT,UPDATE","scheduler.LiveTableSnapshot":"SELECT"}
        for table,rights in permissions.items():
            db.execute(f"GRANT {rights} ON OBJECT::{table} TO [poker_backoffice_app]")
        db.execute("GRANT EXECUTE ON OBJECT::scheduler.SetSchedule TO [poker_backoffice_app]")
        db.execute("GRANT EXECUTE ON OBJECT::scheduler.ExpireOfflineMachines TO [poker_backoffice_app]")
        conn.commit()
    finally:
        conn.close()
    storage=os.environ["StorageConnString"]
    values=dict(p.split("=",1) for p in storage.split(";") if "=" in p)
    service=BlobServiceClient.from_connection_string(storage)
    expiry=datetime.now(timezone.utc)+timedelta(days=90)
    sas=generate_container_sas(service.account_name,"hand-histories",account_key=values["AccountKey"],
        permission=ContainerSasPermissions(read=True),expiry=expiry,
        start=datetime.now(timezone.utc)-timedelta(minutes=5),protocol="https")
    settings.update({"BACKOFFICE_SQL_SERVER":"pokerdbserver.database.windows.net",
        "BACKOFFICE_SQL_DATABASE":"pokerdb","BACKOFFICE_SQL_USER":username,"BACKOFFICE_SQL_PASSWORD":password,
        "BACKOFFICE_HH_CONTAINER_URL":service.get_container_client("hand-histories").url+"?"+sas})
    arm("PUT",RESOURCE+"/config/appsettings",{"properties":settings})
    for key,value in settings.items():
        if key.startswith("BACKOFFICE_SQL_"):
            os.environ[key]=value
    conn=connect()
    try:
        db=Database(conn)
        assert db.one("SELECT COUNT(*) AS n FROM scheduler.Site WHERE CustomerId=14004")["n"]==1
        assert db.one("SELECT HAS_PERMS_BY_NAME('dbo.Customer','OBJECT','UPDATE') AS allowed")["allowed"]==0
    finally:
        conn.close()
    print(json.dumps({"configured":True,"sql_user":username,"storage_read_only":True,"sas_expires":expiry.isoformat()}))


if __name__=="__main__":
    main()
