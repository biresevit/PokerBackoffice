"""Read-only browser checks against preview.py --port 4287 --customer-id 3."""
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT=Path(__file__).resolve().parents[1]/'artifacts'
with sync_playwright() as p:
    browser=p.chromium.launch()
    page=browser.new_page(viewport={'width':1440,'height':1100})
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.route('**/api/**',lambda route:route.continue_() if route.request.method=='GET' else route.abort())
    page.goto('http://127.0.0.1:4287/backoffice/')
    page.get_by_role('heading',name='Overview',exact=True).wait_for()
    page.locator('#entry-chart-filter').wait_for()
    page.get_by_role('tab',name='MTT',exact=True).click()
    page.locator('.mtt-overview').wait_for()
    page.get_by_role('button',name='Custom',exact=True).click()
    page.locator('#entry-chart-filter [name=from]').fill('2026-11-16T18:00')
    page.locator('#entry-chart-filter [name=to]').fill('2026-11-17T00:00')
    with page.expect_response(lambda r:'/mtts/overview?' in r.url and '2026-11-16' in r.url) as response:
        page.get_by_role('button',name='Apply range',exact=True).click()
    data=response.value.json()
    page.get_by_role('row').filter(has_text='Turbo Night').wait_for()
    assert data['hours'] is None
    assert all(i['registration_start']<=data['as_of'] for i in data['items'])
    assert 'Freeroll Pomeriggio' not in [i['name'] for i in data['items']]
    turbo=page.get_by_role('row').filter(has_text='Turbo Night').locator('td').all_text_contents()
    assert turbo[2:]==['Completed','23','23','0','16'],turbo
    assert page.locator('#entry-chart svg').count()==0
    assert page.locator('.mtt-overview-summary strong').all_text_contents()==[str(data['totals'][k]) for k in ('scheduled','registered','running','ever_seated')]
    page.screenshot(path=str(OUT/'mtt-overview-desktop.png'),full_page=True)
    page.get_by_role('tab',name='Ring',exact=True).click()
    page.locator('#entry-chart svg').wait_for()
    assert page.locator('#entry-chart-filter [name=from]').get_attribute('type')=='date'
    page.get_by_role('tab',name='MTT',exact=True).click()
    page.get_by_role('row').filter(has_text='Turbo Night').wait_for()
    page.set_viewport_size({'width':390,'height':900})
    page.screenshot(path=str(OUT/'mtt-overview-mobile.png'),full_page=True)
    for hours in (1,3,6,12,24):
        with page.expect_response(lambda r:'/mtts/overview?' in r.url and f'hours={hours}' in r.url) as res:
            page.get_by_role('button',name=f'Last {hours}h',exact=True).click()
        assert res.value.json()['hours']==hours
        page.locator(f'[data-mtt-hours="{hours}"].active').wait_for()
        assert page.locator('#entry-chart-filter [name=from]').is_disabled()
    page.get_by_role('button',name='Custom',exact=True).click()
    assert page.locator('#entry-chart-filter [name=from]').is_enabled()
    page.locator('#entry-chart-filter [name=from]').fill('2030-01-01T00:00')
    page.locator('#entry-chart-filter [name=to]').fill('2030-01-01T01:00')
    page.get_by_role('button',name='Apply range',exact=True).click()
    page.get_by_text('No MTTs with registration started are active in this time range.',exact=True).wait_for()
    assert not errors,errors
    browser.close()
    print('PASS: historical counts, totals, opened registrations only, time presets, custom timestamps, Ring chart, filter persistence, mobile and future empty state; no writes or browser errors')
