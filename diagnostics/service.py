"""Private broker endpoint. Run on loopback only; never expose this service directly."""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from .agent import investigate
from .data import Data

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.getenv('POKERFILL_DIAGNOSTICS_HISTORY', str(ROOT/'artifacts/diagnostics/history.sqlite3')))
TOKEN = os.getenv('POKERFILL_DIAGNOSTICS_TOKEN', '')
MODE = os.getenv('POKERFILL_DIAGNOSTICS_MODE', 'live')


class Scope(BaseModel):
    model_config = ConfigDict(extra='forbid')
    customer_id: int = Field(gt=0)
    site_id: int = Field(gt=0)
    provider: str = Field(min_length=1, max_length=40)
    subject: str = Field(min_length=1, max_length=200)

    def owner(self):
        return hashlib.sha256(json.dumps(self.model_dump(), sort_keys=True).encode()).hexdigest()


class Inquiry(BaseModel):
    model_config = ConfigDict(extra='forbid')
    scope: Scope
    prompt: str = Field(min_length=3, max_length=2000)
    request_id: uuid.UUID


@contextmanager
def connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        with c: yield c
    finally:
        c.close()


def init():
    with connection() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS investigations(
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, scope TEXT NOT NULL, prompt TEXT NOT NULL,
            status TEXT NOT NULL, created_utc TEXT NOT NULL, result TEXT, error TEXT)''')
        c.execute('CREATE INDEX IF NOT EXISTS ix_owner ON investigations(owner,created_utc)')
        c.execute("UPDATE investigations SET status='failed',error='Local service restarted; submit a new request.' WHERE status IN ('queued','running')")
        c.execute("DELETE FROM investigations WHERE created_utc<?", (datetime.fromtimestamp(time.time()-90*86400,timezone.utc).isoformat(),))


def authorize(authorization):
    if len(TOKEN) < 32 or not hmac.compare_digest(authorization or '', 'Bearer '+TOKEN):
        raise HTTPException(401, 'Private diagnostic broker authentication required')


class RecordedData:
    def __init__(self, scope): self.scope = scope
    def read(self, name, hours=24, tournament='', game_format='RING'):
        values = {'get_schedule_compliance': {'targets': {'RING': 70, 'SNG': 0, 'MTT': 0}, 'entries': [{'format': 'RING', 'status': 'seated', 'count': 0}]},
                  'get_machine_health': [{'MachineId': 5, 'IsReady': True, 'LastHeartbeatUtc': '2026-11-19T15:00:00Z'}],
                  'get_lobby_snapshot': [{'ObservedUtc': '2026-11-19T05:12:00Z', 'TableType': 'RING'}]}
        return {'source': name, 'captured_utc': '2026-11-19T15:00:00Z', 'site_id': self.scope.site_id,
                'coverage': 'Recorded demonstration fixture, not live site data', 'data': values.get(name, {'available': False})}


async def worker(queue):
    while True:
        inquiry = await queue.get()
        rid = str(inquiry.request_id)
        try:
            with connection() as c: c.execute("UPDATE investigations SET status='running' WHERE id=?", (rid,))
            data = RecordedData(inquiry.scope) if MODE == 'recorded' else Data(inquiry.scope)
            result = await asyncio.to_thread(investigate, inquiry.prompt, data, mode=MODE)
            with connection() as c:
                c.execute("UPDATE investigations SET status='completed',result=? WHERE id=?", (json.dumps(result, default=str), rid))
        except Exception as error:
            logging.getLogger(__name__).warning('Investigation failed (%s); sensitive exception details suppressed', type(error).__name__)
            with connection() as c:
                c.execute("UPDATE investigations SET status='failed',error=? WHERE id=?", ('Investigation could not finish. No diagnosis was produced. Check local service configuration and retry.', rid))
        finally:
            queue.task_done()


@asynccontextmanager
async def lifespan(app):
    if len(TOKEN) < 32: raise RuntimeError('Configure a private broker token of at least 32 characters')
    if MODE not in ('live', 'recorded'): raise RuntimeError('Invalid diagnostic mode')
    if MODE == 'live' and not os.getenv('OPENAI_API_KEY'): raise RuntimeError('Configure OPENAI_API_KEY or explicitly select recorded mode')
    init()
    app.state.queue = asyncio.Queue(maxsize=10)
    task = asyncio.create_task(worker(app.state.queue))
    yield
    task.cancel()
    try: await task
    except asyncio.CancelledError: pass


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get('/health')
def health(): return {'status': 'ready', 'mode': MODE}


@app.post('/investigations', status_code=202)
async def create(body: Inquiry, authorization: str = Header(default='')):
    authorize(authorization)
    with connection() as c:
        old = c.execute('SELECT * FROM investigations WHERE id=?', (str(body.request_id),)).fetchone()
        if old:
            if old['owner'] != body.scope.owner(): raise HTTPException(404, 'Request not found')
            if old['prompt'] != body.prompt: raise HTTPException(409, 'Request ID already used')
            return {'id': old['id'], 'status': old['status'], 'mode': MODE}
        if app.state.queue.full(): raise HTTPException(429, 'Diagnostic queue is full; try again later')
        pending = c.execute("SELECT COUNT(*) FROM investigations WHERE owner=? AND status IN ('queued','running')", (body.scope.owner(),)).fetchone()[0]
        recent = c.execute("SELECT COUNT(*) FROM investigations WHERE owner=? AND created_utc>=?", (body.scope.owner(), datetime.fromtimestamp(time.time()-3600, timezone.utc).isoformat())).fetchone()[0]
        if pending >= 2 or recent >= 10: raise HTTPException(429, 'Investigation limit reached; try again later')
        c.execute('INSERT INTO investigations VALUES(?,?,?,?,?,?,NULL,NULL)', (str(body.request_id), body.scope.owner(),
            body.scope.model_dump_json(), body.prompt, 'queued', datetime.now(timezone.utc).isoformat()))
    app.state.queue.put_nowait(body)
    return {'id': str(body.request_id), 'status': 'queued', 'mode': MODE}


@app.post('/history')
def history(scope: Scope, authorization: str = Header(default='')):
    authorize(authorization)
    with connection() as c:
        rows = c.execute('SELECT id,prompt,status,created_utc FROM investigations WHERE owner=? ORDER BY created_utc DESC LIMIT 50', (scope.owner(),)).fetchall()
    return {'items': [dict(r) for r in rows], 'mode': MODE}


@app.post('/investigations/{request_id}')
def detail(request_id: uuid.UUID, scope: Scope, authorization: str = Header(default='')):
    authorize(authorization)
    with connection() as c:
        row = c.execute('SELECT * FROM investigations WHERE id=? AND owner=?', (str(request_id), scope.owner())).fetchone()
    if not row: raise HTTPException(404, 'Request not found')
    return {k: row[k] for k in ('id','prompt','status','created_utc','error')} | {'result': json.loads(row['result']) if row['result'] else None, 'mode': MODE}
