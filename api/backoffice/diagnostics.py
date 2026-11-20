"""Authenticated, short-lived broker to the private diagnostic worker."""
import json
import os
import re
import urllib.request
import urllib.error
from urllib.parse import urlsplit
from uuid import UUID
from .validation import Error


def dispatch(store, site_id, method, tail, body):
    store.site(site_id)
    ctx = store.ctx
    scope = dict(customer_id=ctx.customer_id, site_id=site_id, provider=ctx.provider, subject=ctx.subject)
    base = os.getenv('POKERFILL_DIAGNOSTICS_URL', '').rstrip('/')
    token = os.getenv('POKERFILL_DIAGNOSTICS_TOKEN', '')
    parsed = urlsplit(base)
    if not base or len(token) < 32:
        raise Error(503, 'AI diagnosis is not configured. Start the local diagnostic service first.')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost')):
        raise Error(503, 'The diagnostic service requires a private secure connection')
    if method == 'GET' and tail is None:
        path, payload = '/history', scope
    elif method == 'GET' and re.fullmatch(r'[0-9a-fA-F-]{36}', tail or ''):
        path, payload = '/investigations/'+tail, scope
    elif method == 'POST' and tail is None:
        prompt, rid = body.get('prompt'), body.get('request_id')
        if not isinstance(prompt, str) or not 3 <= len(prompt.strip()) <= 2000:
            raise Error(400, 'Enter a question between 3 and 2000 characters')
        if not isinstance(rid, str) or not re.fullmatch(r'[0-9a-fA-F-]{36}', rid):
            raise Error(400, 'A valid request ID is required')
        try:UUID(rid)
        except ValueError:raise Error(400,'A valid request ID is required') from None
        path, payload = '/investigations', dict(scope=scope, prompt=prompt.strip(), request_id=rid)
        parent=body.get('parent_id')
        if parent is not None:
            if not isinstance(parent,str) or not re.fullmatch(r'[0-9a-fA-F-]{36}',parent):
                raise Error(400,'A valid previous request ID is required')
            try:UUID(parent)
            except ValueError:raise Error(400,'A valid previous request ID is required') from None
            payload['parent_id']=parent
    else:
        raise Error(405, 'Method not allowed')
    request = urllib.request.Request(base+path, data=json.dumps(payload).encode(), method='POST',
        headers={'Content-Type':'application/json', 'Authorization':'Bearer '+token})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return json.loads(response.read(2_000_000))
    except urllib.error.HTTPError as e:
        if e.code==409:
            try:detail=json.loads(e.read(4096)).get('detail')
            except (ValueError,OSError):detail=None
            allowed={'Request ID already used','Open the latest answer before asking a follow-up',
                     'This investigation has reached its question limit; start a new investigation'}
            raise Error(409,detail if detail in allowed else 'Open the latest answer or start a new investigation') from None
        if e.code in (404,409,429):
            raise Error(e.code, {404:'Diagnosis request not found',409:'Request ID already used',429:'Investigation limit reached; try again later'}[e.code])
        raise Error(503, 'Diagnostic service unavailable') from None
    except (OSError, ValueError):
        raise Error(503, 'Diagnostic service unavailable. Check the local worker is running.') from None
