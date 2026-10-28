"""Idempotently add the eight explicitly supplied Evenbet demo accounts."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"api"))
from backoffice.db import session
from backoffice.store import Store,Context

NAMES=("richard","kate","john","jeremy","mason","monica","emma","andrew")
with session() as db:
    store=Store(db,Context(14004,"local","provision-nenad","operator"))
    site=store.site(1)
    assert site["name"]=="Evenbet"
    before=store.accounts(1)
    existing={r["username"].casefold():r for r in before["items"]}
    csv="username,profile\n"+"\n".join(name+","+existing.get(name,{}).get("profile","Strong Balanced") for name in NAMES)
    body={"csv":csv,"mode":"upsert","version":before["version"]}
    preview=store.import_accounts(1,body)
    if any(c["kind"]!="unchanged" for c in preview["changes"]):
        body["token"]=preview["token"]
        store.import_accounts(1,body,apply=True)
    result=[{k:r[k] for k in ("username","profile","stake","max_tables","enabled")} for r in store.accounts(1)["items"] if r["username"] in NAMES]
    assert len(result)==8
print(json.dumps({"customer":"Nenad","site":"Evenbet","accounts":result},indent=2))
