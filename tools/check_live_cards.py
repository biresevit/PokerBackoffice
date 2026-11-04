"""Check the real live view renderer with card sharing on and off."""
from copy import deepcopy
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright, expect

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'api'))
from test_live_cards import table


with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page(viewport={'width':1500,'height':1200})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    payload=table();payload.update(table_name='Card sharing check',max_seats=6,street='Flop',pot=10,dealer=0,acting_seat=None)
    for seat in payload['seats']:seat.update(stack=100,bet=0,sitting_out=False)
    payload['card_sharing']=dict(enabled=True,shared_bots=1)
    payload['seats'][1].update(cards=['kh','kd'],shared_cards=True)
    response=dict(request_id='test',hero='kate',status='active',captured='2026-11-04T20:00:00Z',
                  sequence=1,payload=payload,manual=dict(enabled=False,read_only=True))
    page.route('**/api/sites/1/tables/live/test*',lambda route:route.fulfill(json=deepcopy(response)))
    page.goto('http://127.0.0.1:4298/?live_request=test')
    expect(page.locator('.card-sharing-status')).to_have_text('Card sharing on (1 other bots shown)')
    expect(page.locator('.playing-card[aria-label="kh"]')).to_be_visible()
    expect(page.locator('.playing-card.back')).to_have_count(2)
    Path('artifacts').mkdir(exist_ok=True)
    page.screenshot(path='artifacts/live-cards-sharing-on.png',full_page=True)
    payload['card_sharing']=dict(enabled=False,shared_bots=0)
    payload['seats'][1].update(cards=[],shared_cards=False)
    expect(page.locator('.card-sharing-status')).to_have_count(0)
    expect(page.locator('.playing-card[aria-label="kh"]')).to_have_count(0)
    expect(page.locator('.playing-card.back')).to_have_count(4)
    assert not errors,errors
    browser.close()
    print('Live card sharing browser checks passed')
