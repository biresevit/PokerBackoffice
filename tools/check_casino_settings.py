"""Exercise the actual settings page; settings reads/saves are mocked, not sent to SQL."""
from copy import deepcopy
from pathlib import Path
import json

from playwright.sync_api import sync_playwright,expect


with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1100})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    saved=[]
    data={'casino':'Evenbet','exists':False,'settings':{'use_help':False,'help_min_big_blind':None,'help_min_buy_in':None,
        'solver_vs_humans':False,'solver_min_big_blind':None,'solver_min_buy_in':None,'help_players':[],'solver_players':[]},
        'version':'initial','editable':True,
        'shared':False,'refresh_minutes':10}
    def settings(route):
        if route.request.method=='PUT':
            body=route.request.post_data_json;saved.append(body)
            if body['version']!=data['version']:
                route.fulfill(status=409,json={'error':'Casino settings changed since this page was loaded. Reload before saving.'});return
            data.update(exists=True,version='saved')
            data['settings']={**{k:v for k,v in body.items() if k!='version'},'updated':'2026-11-03T15:00:00Z'}
        route.fulfill(json=data)
    page.route('**/api/sites/*/settings*',settings)
    page.goto('http://127.0.0.1:4298/#settings')
    expect(page.get_by_role('heading',name='Strategy settings',exact=True)).to_be_visible()
    expect(page.get_by_text('No casino settings have been saved.',exact=False)).to_be_visible()
    expect(page.get_by_role('heading',name='Use solver strategy vs humans',exact=True)).to_be_visible()
    page.locator('[name=use_help]').select_option('true')
    page.locator('[name=help_min_big_blind]').fill('4')
    page.locator('[name=help_min_buy_in]').fill('20')
    page.locator('[name=help_players]').fill('player1'+chr(10)+' player2 '+chr(10)+chr(10))
    page.locator('[name=solver_vs_humans]').select_option('true')
    page.locator('[name=solver_min_buy_in]').fill('50')
    page.locator('[name=solver_players]').fill('winner')
    page.get_by_role('button',name='Save settings',exact=True).click()
    expect(page.get_by_text('No casino settings have been saved.',exact=False)).to_have_count(0)
    expect(page.locator('[name=help_min_buy_in]')).to_have_value('20')
    expect(page.locator('[name=solver_players]')).to_have_value('winner')
    assert saved==[dict(version='initial',use_help=True,help_min_big_blind='4',help_min_buy_in='20',help_players=['player1','player2'],
        solver_vs_humans=True,solver_min_big_blind=None,solver_min_buy_in='50',solver_players=['winner'])],saved
    data['version']='changed-elsewhere'
    page.get_by_role('button',name='Save settings',exact=True).click()
    expect(page.get_by_role('alert')).to_contain_text('changed since')
    Path('artifacts').mkdir(exist_ok=True)
    page.screenshot(path='artifacts/casino-settings.png',full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    page.reload()
    expect(page.get_by_role('heading',name='Strategy settings',exact=True)).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
    data['editable']=False
    page.reload()
    expect(page.locator('[name=use_help]')).to_be_disabled()
    expect(page.get_by_role('button',name='Save settings',exact=True)).to_have_count(0)
    assert not errors,errors
    browser.close()
print('Settings editing, payload, save refresh, stale edit, mobile layout and read-only controls passed. No settings written to SQL.')
