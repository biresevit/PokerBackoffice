"""Public landing page, responsive layout, and workspace routing smoke checks."""
from pathlib import Path

from playwright.sync_api import sync_playwright, expect


with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[];api_calls=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda r:api_calls.append(r.url) if '/api/' in r.url else None)
    page.goto('http://127.0.0.1:4298/')
    expect(page.get_by_role('heading',name='Give every player a game to join.')).to_be_visible()
    assert not api_calls,'Public page must not request private customer data'
    page.get_by_role('button',name='0.10 / 0.20',exact=True).click()
    expect(page.locator('[data-demo-stake]')).to_have_text('0.10 / 0.20')
    expect(page.get_by_role('button',name='0.10 / 0.20',exact=True)).to_have_attribute('aria-pressed','true')
    page.get_by_role('button',name='1 / 2',exact=True).click()
    page.get_by_text('Are these automated players?',exact=False).click()
    expect(page.locator('details[open]')).to_contain_text('Yes. Poker Control manages poker bots')
    # Every local fragment link must have a destination.
    assert page.evaluate('''() => [...document.querySelectorAll('a[href^="#"]')].every(a=>document.getElementById(a.hash.slice(1)))''')
    for width in (1440,1024,768,390,320):
        page.set_viewport_size({'width':width,'height':1000})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'Overflow at {width}px'
        if width in (1440,390):
            page.screenshot(path=f'artifacts/home-{width}.png',full_page=True)
    page.set_viewport_size({'width':1440,'height':1000})
    page.goto('http://127.0.0.1:4298/')
    page.screenshot(path='artifacts/home-hero.png')
    # An anonymous visitor can reach the sign-in screen, with no customer data.
    page.route('**/api/me*',lambda route:route.fulfill(status=401,json={'error':'Sign in required'}))
    page.get_by_role('link',name='Customer sign in').click()
    expect(page.get_by_role('link',name='Continue with Microsoft')).to_have_attribute('href','/.auth/login/aad?post_login_redirect_uri=/backoffice')
    assert page.url.endswith('/backoffice')
    page.goto('http://127.0.0.1:4298/#accounts')
    page.wait_for_url('**/backoffice#accounts')
    page.goto('http://127.0.0.1:4298/?live_request=legacy&site_id=1')
    page.wait_for_url('**/backoffice?live_request=legacy&site_id=1')
    assert not errors,errors
    browser.close()
    print('Public home, mobile layouts, sign-in and legacy routing passed')
