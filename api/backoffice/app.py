from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from .db import session
from .histories import Histories
from .store import Context, Store, memberships
from .validation import Error, PROFILES, integer

log = logging.getLogger(__name__)


@dataclass
class Request:
    method: str
    path: str
    headers: dict = field(default_factory=dict)
    query: dict = field(default_factory=dict)
    body: bytes = b""


@dataclass
class Response:
    status: int
    body: bytes
    headers: dict


def json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(type(value).__name__)


def response(body, status=200):
    return Response(status, json.dumps(body, default=json_default, ensure_ascii=False).encode(),
                    {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


def principal(headers):
    # This entry point is deployed ONLY as a SWA managed API. The SWA edge owns
    # this header; do not expose the function as a separate public HTTP service.
    raw = headers.get("x-ms-client-principal", "")
    try:
        value = json.loads(base64.b64decode(raw, validate=True))
        if (not isinstance(value, dict) or value.get("identityProvider") != "aad"
            or not isinstance(value.get("userRoles"), list) or "authenticated" not in value.get("userRoles", [])
            or not isinstance(value.get("userId"), str) or not 1 <= len(value["userId"]) <= 200):
            raise ValueError()
        return value
    except (ValueError, TypeError, KeyError):
        raise Error(401, "Sign in with Microsoft to continue")


def handle(request: Request, session_factory=session, *, local_context: Context | None = None):
    try:
        # Public readiness probe exposes no identities or customer data.
        if request.path == "/api/health" and request.method == "GET":
            with session_factory() as db:
                db.one("SELECT TOP(1) 1 AS ok FROM backoffice.Membership")
            return response({"status": "ready"})
        headers = {k.lower(): v for k, v in request.headers.items()}
        if request.path == '/api/contact':
            if request.method != 'POST':
                raise Error(405, 'Method not allowed')
            from .contact import submit
            return response(submit(request.body, headers, session_factory))
        setup=re.fullmatch(r"/api/setup/(request|poll|complete|restore)",request.path)
        if setup:
            if request.method!='POST':raise Error(405,'Method not allowed')
            if len(request.body)>16384:raise Error(413,'Request is too large')
            try:
                setup_body=json.loads(request.body or b'{}')
                if not isinstance(setup_body,dict):raise ValueError()
            except (ValueError,UnicodeError):raise Error(400,'Invalid setup request')
            from .pairing import public_request
            with session_factory() as db:
                return response(public_request(db,setup[1],setup_body,headers.get('x-forwarded-for','unknown').split(',')[0].strip()))
        updater=re.fullmatch(r"/api/updater/(\d+)/(poll|report|status|logs-poll|logs-report)",request.path)
        if updater:
            if request.method!='POST':raise Error(405,'Method not allowed')
            if len(request.body)>32768:raise Error(413,'Request is too large')
            try:
                agent_body=json.loads(request.body or b'{}')
                if not isinstance(agent_body,dict):raise ValueError()
            except (ValueError,UnicodeError):raise Error(400,'Invalid updater request')
            from .updates import agent_request
            with session_factory() as db:
                return response(agent_request(db,int(updater[1]),headers,agent_body,updater[2]))
        user = principal(headers) if local_context is None else {
            "identityProvider": local_context.provider, "userId": local_context.subject, "userDetails": "Local preview"}
        if len(request.body) > 2 * 1024 * 1024:
            raise Error(413, "Request is too large")
        body = {}
        if request.method in ("POST", "PUT", "DELETE"):
            if headers.get("x-requested-with") != "PokerBackoffice" or not headers.get("content-type", "").startswith("application/json"):
                raise Error(403, "A same-origin JSON request is required")
            try:
                body = json.loads(request.body or b"{}")
            except (ValueError, UnicodeError):
                raise Error(400, "Invalid JSON")
            if not isinstance(body, dict):
                raise Error(400, "JSON body must be an object")
        path = request.path.removeprefix("/api").strip("/")
        with session_factory() as db:
            member = memberships(db, user) if local_context is None else [
                {"id": local_context.customer_id, "name": db.one("SELECT CustomerName FROM dbo.Customer WHERE CustomerId=%s", local_context.customer_id)["CustomerName"], "role": local_context.role}]
            if path == "me" and request.method == "GET":
                return response({"memberships": member, "user": {"name": user.get("userDetails", ""), "subject": user["userId"],
                                 "provider": user["identityProvider"]}, "profiles": PROFILES, "local_preview": local_context is not None})
            if path == "access-request" and request.method == "POST":
                existing = db.one("SELECT Subject FROM backoffice.AccessRequest WITH(UPDLOCK,HOLDLOCK) WHERE Provider=%s AND Subject=%s", user["identityProvider"], user["userId"])
                if not existing:
                    db.execute("INSERT backoffice.AccessRequest(Provider,Subject,UserDetails) VALUES(%s,%s,%s)",
                               user["identityProvider"], user["userId"], str(user.get("userDetails", ""))[:254])
                return response({"requested": True})
            cid = integer(request.query.get("customer_id", member[0]["id"] if member else 0), 0, field="customer")
            membership = next((m for m in member if m["id"] == cid), None)
            if not membership:
                raise Error(403, "Your Microsoft account has not been granted access to this customer")
            store = Store(db, Context(cid, user["identityProvider"], user["userId"], membership["role"]))
            if path == "sites" and request.method == "GET":
                return response({"items": store.sites()})
            match = re.fullmatch(r"sites/(\d+)/(overview|metrics|accounts|schedule|stakes|tables|machines|tasks|sessions|histories|chat|updates|settings|mtts|monitoring)(?:/(.*))?", path)
            if not match:
                raise Error(404, "Endpoint not found")
            sid, section, tail = int(match[1]), match[2], match[3]
            # Scope checked before any resource-specific query (including downloads).
            store.site(sid)
            method = request.method
            logs=re.fullmatch(r'(\d+)/logs(?:/([0-9a-fA-F-]+)/download)?',tail or '') if section=='machines' else None
            if logs:
                from .machine_logs import MachineLogs
                service=MachineLogs(store);mid=int(logs[1])
                if method=='GET' and logs[2]:return response(service.download(sid,mid,logs[2]))
                if method=='GET' and not logs[2]:return response(service.list(sid,mid))
                if method=='POST' and not logs[2]:return response(service.create(sid,mid,body),202)
                raise Error(405,'Method not allowed')
            if section == 'settings':
                from .casino_settings import CasinoSettings
                settings=CasinoSettings(store)
                if method=='GET' and tail is None:return response(settings.get(sid))
                if method=='PUT' and tail is None:return response(settings.save(sid,body))
                raise Error(405,'Method not allowed')
            if section == "updates":
                from .updates import Updates
                updates=Updates(store)
                if method=='GET' and tail is None:return response(updates.list(sid,request.query))
                if method=='POST' and tail is None:return response(updates.create(sid,body),202)
                if method=='POST' and tail in ('pairing/lookup','pairing/approve'):
                    from .pairing import lookup,approve
                    return response((lookup if tail.endswith('lookup') else approve)(store,sid,body))
                if method=='POST' and tail=='enroll':return response(updates.enroll(sid,body))
                if method=='POST' and tail:return response(updates.control(sid,tail,body))
                raise Error(405,'Method not allowed')
            if section == "chat":
                from .chat import Chat
                chat=Chat(store)
                if method=="GET" and tail is None:
                    return response(chat.summary(sid))
                parts=(tail or '').split('/')
                table_id=parts[0]
                if method=="GET" and len(parts)==1:
                    return response(chat.messages(sid,table_id,request.query))
                if method=="POST" and len(parts)==2 and parts[1]=='read':
                    return response(chat.read(sid,table_id,body))
                if method=="POST" and len(parts)==2 and parts[1]=='send':
                    return response(chat.send(sid,table_id,body),202)
                raise Error(404,'Chat endpoint not found')
            if section == "histories":
                hh = Histories(store)
                if method == "GET" and tail is None:
                    return response(hh.list(sid, request.query))
                if method == "GET" and tail and tail.isdecimal():
                    return response(hh.detail(sid, int(tail)))
                if method == "GET" and tail == "report":
                    return response(hh.report(sid, request.query))
                if method == "POST" and tail == "download":
                    return Response(200, hh.download(sid, body.get("ids"), body.get("filters") if body.get("all") is True else None), {"Content-Type": "application/zip", "Cache-Control": "no-store",
                        "Content-Disposition": 'attachment; filename="hand-histories.zip"', "X-Content-Type-Options": "nosniff"})
            if section == "tables":
                control=re.fullmatch(r"live/([0-9a-fA-F-]+)/(manual|action)",tail or '')
                if method=='POST' and control:
                    from .manual import Manual
                    return response(getattr(Manual(store),'mode' if control[2]=='manual' else 'action')(sid,control[1],body))
                if method == "POST" and tail == "live":
                    return response(store.request_live_view(sid,body.get("table_id"),body.get("account_id")))
                if method == "GET" and tail and tail.startswith("live/"):
                    return response(store.live_view(sid,tail.removeprefix("live/")))
            if section == "metrics" and method == "GET" and tail is None:
                return response(store.entry_metrics(sid,request.query))
            if section == "sessions" and (tail is not None or method == "POST"):
                from .sessions import Sessions
                sessions=Sessions(store)
                if method=="GET" and tail=="options":
                    return response(sessions.options(sid))
                if method=="POST" and tail is None:
                    return response(sessions.create(sid,body),201)
                stop=re.fullmatch(r"([0-9a-fA-F-]+)/stop",tail or '')
                if method=="POST" and stop:
                    return response(sessions.stop(sid,stop[1]))
                raise Error(404,'Session endpoint not found')
            if section == "tasks" and (tail is not None or method == "POST"):
                from .manual_tasks import ManualTasks
                tasks=ManualTasks(store)
                if method=="GET" and tail=="options":
                    return response(tasks.options(sid))
                if method=="GET" and tail=="join-candidates":
                    return response(tasks.join_candidates(sid,request.query.get('table_id')))
                if method=="POST" and tail is None:
                    return response(tasks.create(sid,body),201)
                raise Error(404,'Task endpoint not found')
            if section in ("tasks","sessions") and method == "GET" and tail is None:
                return response(getattr(store,section)(sid,request.query))
            if section == "machines" and method == "GET" and tail:
                metric_match = re.fullmatch(r"(\d+)/metrics", tail)
                if metric_match:
                    return response(store.machine_metrics(sid, int(metric_match[1]), request.query))
            if section == "monitoring" and tail is None and method == "GET":
                from .monitoring import Monitoring
                return response(Monitoring(store).get(sid, request.query))
            if section == "mtts" and tail == "overview" and method == "GET":
                from .mtts import Mtts
                return response(Mtts(store).overview(sid,request.query))
            if section == "mtts" and tail is None:
                from .mtts import Mtts
                mtts = Mtts(store)
                if method == "GET":
                    return response(mtts.list(sid))
                if method == "PUT":
                    return response(mtts.save(sid, body))
                if method == "DELETE":
                    return response(mtts.delete(sid, body))
                raise Error(405, "Method not allowed")
            if method == "GET" and tail is None and section == "schedule":
                return response(store.schedule(sid, request.query.get("format") or "RING"))
            if method == "GET" and tail is None and section in ("overview", "accounts", "stakes", "tables", "machines"):
                return response(getattr(store, section)(sid))
            if section == "accounts":
                if method == "POST" and tail == "bulk":
                    from .distributions import Distributions
                    return response(Distributions(store).bulk_set(sid, body))
                if method == "POST" and tail in ("import-preview", "import"):
                    return response(store.import_accounts(sid, body, apply=tail == "import"))
                if tail and (tail == "distributions" or tail.startswith("distributions/")):
                    from .distributions import Distributions
                    dist = Distributions(store)
                    rest = tail.removeprefix("distributions").strip("/")
                    if method == "GET" and not rest:
                        return response(dist.list(sid))
                    if method == "POST" and rest in ("preview", "apply"):
                        return response(dist.preview(sid, body) if rest == "preview" else dist.apply(sid, body))
                    if method == "PUT" and rest:
                        return response(dist.save(sid, rest, body))
                    raise Error(404, "Distribution endpoint not found")
                if tail and tail.isdecimal():
                    if method == "PUT":
                        return response(store.update_account(sid, int(tail), body))
                    if method == "DELETE":
                        return response(store.delete_account(sid, int(tail), body))
            if method == "PUT" and section == "schedule" and tail == "pause":
                return response(store.pause_joins(sid, body))
            if method == "PUT" and tail is None and section in ("schedule", "stakes"):
                return response(getattr(store, "save_" + section)(sid, body))
            if method == "PUT" and section == "machines" and tail and tail.isdecimal():
                return response(store.save_machine(sid, int(tail), body))
            if method == "DELETE" and section == "machines" and tail and tail.isdecimal():
                return response(store.delete_machine(sid, int(tail), body))
            raise Error(405, "Method not allowed")
    except Error as exc:
        return response({"error": exc.message}, exc.status)
    except Exception:
        # Avoid returning SQL text, connection details, or storage credentials.
        log.exception("Backoffice request failed")
        return response({"error": "The request could not be completed. Please try again."}, 500)
