"""Check quote submission locally with intercepted API calls; no email is sent."""
import sys
from pathlib import Path
from urllib.parse import urlsplit,parse_qs

from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'api'))
from backoffice.validation import parse_csv

assert parse_csv((ROOT/'frontend/bot-account-template.csv').read_text())==[
    {'username':'bot_001','strategy':5},{'username':'bot_002','strategy':6},
    {'username':'bot_003','strategy':2}]

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[];api_calls=[];enquiries=[];failures=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda r:api_calls.append(r.url) if '/api/' in r.url else None)
    def contact_route(route):
        enquiries.append(route.request.post_data_json)
        route.fulfill(status=503 if failures else 200,
                      json={'error':'Email is temporarily unavailable.'} if failures else {'sent':True})
    page.route('**/api/contact',contact_route)
    page.add_init_script('''
      window.quoteDrafts=[];
      const original=HTMLAnchorElement.prototype.click;
      HTMLAnchorElement.prototype.click=function(){
        if(this.protocol==='mailto:'){window.quoteDrafts.push(this.href);return;}
        return original.call(this);
      };
    ''')
    page.goto('http://127.0.0.1:4298/')
    expect(page.locator('.hero-note')).to_contain_text('One-month free trial')
    page.locator('.hero-actions .primary').click()
    page.wait_for_url('**/#contact')
    submit=page.get_by_role('button',name='Request a custom quote',exact=False)
    submit.click()
    assert not enquiries
    page.locator('[name=contact_name]').fill('Example Operator')
    page.locator('[name=contact_email]').fill('owner@example.com')
    page.locator('[name=site]').fill('Example Poker')
    page.locator('[name=platform]').fill('Evenbet')
    page.locator('[name=bots]').fill('100')
    page.locator('[name=stakes]').fill('0.10 / 0.20 to 1 / 2')
    page.locator('[name=notes]').fill('Evening traffic, Europe/Budapest. NLH & PLO.')
    page.locator('[name=games][value="Cash games"]').uncheck()
    submit.click()
    expect(page.locator('#quote-error')).to_have_text('Select at least one game format.')
    assert not enquiries
    page.locator('[name=games][value=MTT]').check()
    failures.append(True)
    submit.click()
    expect(page.locator('#quote-error')).to_contain_text('Email is temporarily unavailable.')
    assert page.locator('[name=contact_name]').input_value()=='Example Operator'
    assert page.evaluate('quoteDrafts.length')==0
    uri=urlsplit(page.locator('#quote-email-draft').get_attribute('href'));query=parse_qs(uri.query)
    assert uri.scheme=='mailto' and uri.path=='support@pokerfill.com'
    assert query['subject']==['PokerFill quote and trial enquiry']
    body=query['body'][0]
    for text in ('Example Operator','owner@example.com','Example Poker','Evenbet',
                 'Estimated bots needed: 100','Game formats: MTT','NLH & PLO.',
                 'one-month free trial: Yes','provide and fund the bot accounts'):
        assert text in body,text
    page.locator('[name=trial]').uncheck()
    page.locator('[name=bots]').fill('0')
    submit.click();assert len(enquiries)==1
    page.locator('[name=bots]').fill('20')
    failures.clear()
    submit.click()
    expect(page.locator('#quote-status')).to_contain_text('Your enquiry has been sent')
    assert enquiries[-1]['trial'] is False and enquiries[-1]['bots']=='20'
    assert enquiries[-1]['games']==['MTT']
    assert page.locator('[name=contact_name]').input_value()==''
    expect(page.locator('#quote-email-draft')).to_be_hidden()
    page.locator('#contact').screenshot(path='artifacts/home-quote-desktop.png')
    page.locator('#getting-started').screenshot(path='artifacts/home-onboarding.png')
    for width in (1024,768,390,320):
        page.set_viewport_size({'width':width,'height':1000})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
    page.set_viewport_size({'width':390,'height':1000})
    page.locator('#contact').screenshot(path='artifacts/home-quote-mobile.png')
    assert len(api_calls)==2 and all(url.endswith('/api/contact') for url in api_calls) and not errors,(api_calls,errors)
    browser.close()
    print('Direct quote submission, SMTP-error fallback, trial terms, CSV, validation and mobile passed; no email sent')
