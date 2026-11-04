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
    expect(page.get_by_role('heading',name='Complete poker bot solution for operators.')).to_be_visible()
    assert not api_calls,'Public page must not request private customer data'
    page.get_by_role('button',name='0.10 / 0.20',exact=True).click()
    expect(page.locator('[data-demo-stake]')).to_have_text('0.10 / 0.20')
    expect(page.get_by_role('button',name='0.10 / 0.20',exact=True)).to_have_attribute('aria-pressed','true')
    page.get_by_role('button',name='1 / 2',exact=True).click()
    assert page.locator('.profile-card').count()==8
    expect(page.locator('.profile-card').first).to_contain_text('Maniac')
    expect(page.locator('.profile-card').first.locator('dd')).to_have_text(['60%','40%','20%','80%'])
    page.get_by_role('button',name='200 automated entries',exact=True).click()
    expect(page.locator('[data-mtt-pool]')).to_have_text('$2,200')
    expect(page.locator('[data-mtt-funding]')).to_have_text('$2,000')
    expect(page.locator('[data-mtt-field]')).to_have_text('220')
    page.get_by_role('button',name='100 automated entries',exact=True).click()
    expect(page.locator('[data-mtt-pool]')).to_have_text('$1,200')
    page.locator('#profiles').screenshot(path='artifacts/home-profiles.png')
    page.locator('#tournaments').screenshot(path='artifacts/home-tournaments.png')
    expect(page.get_by_role('tab')).to_have_count(8)
    for tab in page.get_by_role('tab').all():
        tab.click()
        image=page.locator('#screenshot-image')
        image.scroll_into_view_if_needed()
        expect(image).to_be_visible()
        page.wait_for_function('document.querySelector("#screenshot-image").naturalWidth>0')
        assert image.evaluate('img=>img.complete && img.naturalWidth===Number(img.getAttribute("width"))')
    page.get_by_role('tab',name='Overview',exact=True).click()
    page.locator('#screenshot-open').click()
    dialog=page.locator('#screenshot-dialog')
    expect(dialog).to_be_visible()
    page.get_by_role('button',name='Zoom in',exact=True).click()
    expect(page.locator('#screenshot-zoom')).to_have_attribute('aria-pressed','true')
    page.wait_for_function('document.querySelector("#screenshot-full").naturalWidth>0')
    assert page.locator('#screenshot-viewport').evaluate('e=>e.scrollWidth>e.clientWidth')
    page.get_by_role('button',name='Fit to screen',exact=True).click()
    page.keyboard.press('ArrowRight')
    expect(page.locator('#screenshot-dialog-title')).to_have_text('Player settings')
    page.locator('#screenshot-prev').click()
    expect(page.locator('#screenshot-dialog-title')).to_have_text('Overview')
    page.keyboard.press('Escape')
    expect(dialog).to_be_hidden()
    expect(page.locator('#screenshot-open')).to_be_focused()
    page.get_by_role('tab',name='Manual control',exact=True).click()
    page.locator('#platform').screenshot(path='artifacts/home-manual-screenshot.png')
    page.get_by_role('tab',name='Manual control',exact=True).focus()
    page.keyboard.press('ArrowRight')
    expect(page.get_by_role('tab',name='Table chat',exact=True)).to_have_attribute('aria-selected','true')
    expect(page.locator('#screenshot-image')).to_have_attribute('src','/product-shots/chat.png')
    page.locator('#platform').screenshot(path='artifacts/home-chat-screenshot.png')
    assert not api_calls,'Public screenshots must never call the private APIs'
    page.get_by_text('Are these automated players?',exact=False).click()
    expect(page.locator('details[open]')).to_contain_text('Yes. PokerFill manages poker bots')
    # Every local fragment link must have a destination.
    assert page.evaluate('''() => [...document.querySelectorAll('a[href^="#"]')].every(a=>document.getElementById(a.hash.slice(1)))''')
    for width in (1440,1024,768,390,320):
        page.set_viewport_size({'width':width,'height':1000})
        for tab in page.get_by_role('tab').all():
            tab.click()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'Overflow at {width}px'
        if width in (1440,390):
            page.screenshot(path=f'artifacts/home-{width}.png',full_page=True)
        if width==390:
            page.get_by_role('tab',name='Manual control',exact=True).click()
            page.locator('#screenshot-open').click()
            expect(dialog).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.locator('#screenshot-next').click()
            expect(page.locator('#screenshot-dialog-title')).to_have_text('Table chat')
            page.get_by_role('button',name='Close',exact=False).click()
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
