import json
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from backoffice import contact
from backoffice.app import Request, handle
from backoffice.validation import Error


HEADERS = {'content-type': 'application/json', 'x-requested-with': 'PokerFill',
           'origin': 'https://pokerfill.com', 'x-forwarded-for': '192.0.2.1'}
DATA = dict(contact_email='operator@example.com', site='Example Poker',
            bots='100', games=['SNG', 'MTT'], trial=True, notes='Evening traffic',
            preferred_start='2026-12-01T14:30', timezone='Europe/Budapest', website='')


def test_email_uses_fixed_recipient_and_visitor_reply_to(monkeypatch):
    smtp = MagicMock()
    smtp.return_value.__enter__.return_value.send_message.return_value = {}
    monkeypatch.setattr(contact.smtplib, 'SMTP_SSL', smtp)
    contact.send_enquiry(contact.parse_enquiry(json.dumps(DATA).encode(), HEADERS), 'test-secret')
    assert smtp.call_args.args == ('mail.privateemail.com', 465)
    assert smtp.call_args.kwargs['context'].check_hostname
    connection = smtp.return_value.__enter__.return_value
    connection.login.assert_called_once_with(contact.MAILBOX, 'test-secret')
    call = connection.send_message.call_args
    message = call.args[0]
    assert str(message['To']) == contact.MAILBOX
    assert str(message['Reply-To']) == DATA['contact_email']
    assert call.kwargs == {'from_addr': contact.MAILBOX, 'to_addrs': [contact.MAILBOX]}
    assert 'Game formats: SNG, MTT' in message.get_content()
    assert 'free trial: Yes' in message.get_content()
    assert '2026-12-01 14:30 (Europe/Budapest)' in message.get_content()
    assert 'Contact:' not in message.get_content() and 'Preferred stakes:' not in message.get_content()


@pytest.mark.parametrize('patch', [
    {'contact_email': 'x@example.com\r\nBcc:other@example.com'}, {'contact_email': 'invalid'},
    {'contact_email': ''}, {'notes': 'x'*1501}, {'bots': 0}, {'bots': True},
    {'bots': 100001}, {'games': []}, {'games': ['Cash games', 'other']},
    {'games': ['MTT', 'MTT']}, {'games': [{}]}, {'trial': 'yes'},
    {'preferred_start': '2026-02-30T14:30'}, {'preferred_start': 'tomorrow'},
    {'timezone': 'Unknown/Zone'}, {'timezone': ''}])
def test_invalid_input_rejected(patch):
    with pytest.raises(Error) as error:
        contact.parse_enquiry(json.dumps(dict(DATA, **patch)).encode(), HEADERS)
    assert error.value.status == 400


@pytest.mark.parametrize('patch', [{'origin': 'https://other.example'},
    {'x-requested-with': ''}, {'content-type': 'text/plain'}, {'sec-fetch-site': 'cross-site'}])
def test_cross_origin_requests_rejected(patch):
    result = handle(Request('POST', '/api/contact', dict(HEADERS, **patch), body=json.dumps(DATA).encode()))
    assert result.status == 403


def test_private_enquiry_needs_no_name_site_platform_stakes_or_start():
    data = {'contact_email': 'private@example.com', 'bots': '20', 'games': ['Cash games'], 'trial': True}
    parsed = contact.parse_enquiry(json.dumps(data).encode(), HEADERS)
    assert parsed['site'] == '' and parsed['preferred_start'] == ''
    assert not {'contact_name', 'platform', 'stakes'} & parsed.keys()


def test_public_route_needs_no_identity_and_commits_limit_before_smtp(monkeypatch):
    events = []
    @contextmanager
    def session():
        events.append('open')
        yield object()
        events.append('committed')
    monkeypatch.setenv('POKERFILL_SMTP_PASSWORD', 'test-secret')
    monkeypatch.setattr(contact, 'reserve_attempt', lambda *a: events.append('reserve'))
    monkeypatch.setattr(contact, 'send_enquiry', lambda *a: events.append('smtp'))
    result = handle(Request('POST', '/api/contact', HEADERS, body=json.dumps(DATA).encode()), session)
    assert result.status == 200 and json.loads(result.body) == {'sent': True}
    assert events == ['open', 'reserve', 'committed', 'smtp']
    assert handle(Request('GET', '/api/contact')).status == 405
    assert handle(Request('GET', '/api/sites')).status == 401


def test_missing_credentials_and_honeypot_never_connect(monkeypatch):
    monkeypatch.delenv('POKERFILL_SMTP_PASSWORD', raising=False)
    def fail():
        pytest.fail('Database accessed')
    for data, expected in [(DATA, 503), (dict(DATA, website='spam'), 200)]:
        assert handle(Request('POST', '/api/contact', HEADERS, body=json.dumps(data).encode()), fail).status == expected


def test_smtp_failure_does_not_claim_delivery_or_leak_secret(monkeypatch):
    smtp = MagicMock(side_effect=contact.smtplib.SMTPAuthenticationError(535, b'private details'))
    monkeypatch.setattr(contact.smtplib, 'SMTP_SSL', smtp)
    with pytest.raises(Error) as error:
        contact.send_enquiry(DATA, 'test-secret')
    assert error.value.status == 503
    assert 'private details' not in error.value.message
    assert 'test-secret' not in error.value.message


def test_rate_limit_rejects_before_sending_and_hashes_ip():
    db = MagicMock()
    db.one.side_effect = [{'result': 0}, {'Attempts': 5}]
    with pytest.raises(Error) as error:
        contact.reserve_attempt(db, HEADERS)
    assert error.value.status == 429
    assert '192.0.2.1' not in str(db.mock_calls)
    db.execute.assert_not_called()
