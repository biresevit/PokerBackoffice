"""Public quote enquiries. Fixed mailbox destination; no customer data access."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import re
import smtplib
import ssl
import certifi
from datetime import datetime, timezone
from email.message import EmailMessage

from .validation import Error

MAILBOX = 'support@pokerfill.com'
log = logging.getLogger(__name__)
ORIGINS = {'https://pokerfill.com', 'https://www.pokerfill.com',
           'https://lively-rock-032158003.4.azurestaticapps.net'}


def parse_enquiry(raw, headers):
    if len(raw) > 16384:
        raise Error(413, 'Your enquiry is too large.')
    if (headers.get('x-requested-with') != 'PokerFill'
            or headers.get('content-type', '').split(';')[0].strip() != 'application/json'
            or headers.get('origin') not in ORIGINS | {None}
            or headers.get('sec-fetch-site') == 'cross-site'):
        raise Error(403, 'Please submit the form from the PokerFill website.')
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError()
    except (ValueError, UnicodeError):
        raise Error(400, 'Invalid enquiry.')
    # Quietly discard automated submissions filling the hidden company URL field.
    if data.get('website'):
        return None
    fields = {}
    for name, limit, required in [('contact_name', 100, True), ('contact_email', 150, True),
            ('site', 120, True), ('platform', 100, True), ('stakes', 120, False),
            ('notes', 1500, False)]:
        value = data.get(name, '')
        if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
            raise Error(400, 'Please check the required fields and their lengths.')
        if any(ord(c) < 32 and c not in '\r\n\t' for c in value):
            raise Error(400, 'Invalid characters in enquiry.')
        fields[name] = value.strip()
    email = fields['contact_email']
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}", email):
        raise Error(400, 'Please enter a valid email address.')
    bots = data.get('bots')
    if isinstance(bots, bool) or not re.fullmatch(r'[0-9]{1,6}', str(bots)) or not 1 <= int(bots) <= 100000:
        raise Error(400, 'Enter a bot count between 1 and 100,000.')
    games = data.get('games')
    if (not isinstance(games, list) or not 1 <= len(games) <= 3
            or any(not isinstance(g, str) or g not in ('Cash games', 'SNG', 'MTT') for g in games)
            or len(set(games)) != len(games)):
        raise Error(400, 'Select at least one game format.')
    if not isinstance(data.get('trial'), bool):
        raise Error(400, 'Invalid trial selection.')
    return dict(fields, bots=int(bots), games=games, trial=data['trial'])


def reserve_attempt(db, headers):
    # SWA owns x-forwarded-for on this managed API. Treat IPv6 /64 as one source.
    source = headers.get('x-forwarded-for', '').split(',')[0].strip()
    try:
        addr = ipaddress.ip_address(source)
        source = str(ipaddress.ip_network(f'{addr}/64', strict=False)) if addr.version == 6 else str(addr)
    except ValueError:
        source = 'unknown'
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    buckets = [('ip:'+source, now.replace(minute=0, second=0, microsecond=0), 5),
               ('global', now.replace(hour=0, minute=0, second=0, microsecond=0), 100)]
    lock = db.one("""DECLARE @result int;
        EXEC @result=sys.sp_getapplock @Resource='PokerFillContactRate',
        @LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=5000;
        SELECT @result AS result""")
    if not lock or lock['result'] < 0:
        raise Error(503, 'Please try again shortly, or email support@pokerfill.com.')
    for key, window, limit in buckets:
        digest = hashlib.sha256(key.encode()).hexdigest()
        row = db.one('SELECT Attempts FROM backoffice.ContactRateLimit WHERE Bucket=%s AND WindowStart=%s', digest, window)
        if row and row['Attempts'] >= limit:
            raise Error(429, 'Too many enquiries. Please try later or email support@pokerfill.com.')
        if row:
            db.execute('UPDATE backoffice.ContactRateLimit SET Attempts=Attempts+1 WHERE Bucket=%s AND WindowStart=%s', digest, window)
        else:
            db.execute('INSERT backoffice.ContactRateLimit(Bucket,WindowStart,Attempts) VALUES(%s,%s,1)', digest, window)
    db.execute('DELETE backoffice.ContactRateLimit WHERE WindowStart<DATEADD(day,-2,SYSUTCDATETIME())')


def send_enquiry(data, password):
    message = EmailMessage()
    message['From'] = f'PokerFill website <{MAILBOX}>'
    message['To'] = MAILBOX
    message['Reply-To'] = data['contact_email']
    message['Subject'] = 'PokerFill quote and trial enquiry'
    message.set_content('\n'.join([
        'A new enquiry was submitted on the PokerFill website.', '',
        f"Contact: {data['contact_name']}", f"Work email: {data['contact_email']}",
        f"Poker site / company: {data['site']}", f"Platform / software: {data['platform']}",
        f"Estimated bots needed: {data['bots']}", f"Game formats: {', '.join(data['games'])}",
        f"Preferred stakes: {data['stakes'] or 'To discuss'}",
        f"Interested in the one-month free trial: {'Yes' if data['trial'] else 'Not at this stage'}",
        '', 'Traffic plan, timezone and other requirements:', data['notes'] or 'To discuss', '',
        'Trial terms shown to the visitor: compatibility review required; operator provides and funds bot accounts.'
    ]))
    try:
        with smtplib.SMTP_SSL('mail.privateemail.com', 465,
                              context=ssl.create_default_context(cafile=certifi.where()), timeout=15) as client:
            client.login(MAILBOX, password)
            refused = client.send_message(message, from_addr=MAILBOX, to_addrs=[MAILBOX])
            if refused:
                raise smtplib.SMTPException('Recipient refused')
    except (OSError, smtplib.SMTPException):
        # Don't log SMTP responses, which may contain credentials or enquiry content.
        log.warning('Contact email delivery failed')
        raise Error(503, 'We could not confirm delivery. Please email support@pokerfill.com directly.')


def submit(raw, headers, session_factory):
    data = parse_enquiry(raw, headers)
    if data is None:
        return {'sent': True}
    password = os.environ.get('POKERFILL_SMTP_PASSWORD')
    if not password:
        raise Error(503, 'Please email support@pokerfill.com directly while the form is being configured.')
    # Commit rate limits before SMTP; never hold a database transaction while sending.
    with session_factory() as db:
        reserve_attempt(db, headers)
    send_enquiry(data, password)
    return {'sent': True}
