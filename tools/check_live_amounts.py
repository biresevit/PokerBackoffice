"""Display-only regression: mock every API call, never send a poker action."""
from copy import deepcopy
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page(viewport={'width':1400,'height':1100},locale='en-US')
    errors=[];writes=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    payload={'tournament':True,'table_id':'42','table_name':'SNG Sandstorm','hero':'andrew',
             'hand_id':'100','game':'NLH','street':'Flop','max_seats':6,'pot':7.5,
             'big_blind':1,'board':[],'dealer':1,'acting_seat':None,
             'manual':{'supported':False,'enabled':False},
             'seats':[{'seat':0,'name':'andrew','stack':10,'bet':.5,'cards':[],'hero':True},
                      {'seat':1,'name':'john','stack':9,'bet':1,'cards':[],'hero':False}],
             'result':{'hand_id':'99','winners':[{'seat':1,'name':'john','amount':2.5}]}}
    def api(route):
        req=route.request
        if req.method!='GET':writes.append(req.url);route.abort();return
        path=urlsplit(req.url).path
        if path.endswith('/me'):
            route.fulfill(json={'memberships':[{'id':14004,'name':'Nenad','role':'operator'}]})
        elif path.endswith('/sites'):
            route.fulfill(json={'items':[{'id':1,'name':'Evenbet','timezone':'Europe/Budapest'}]})
        elif '/tables/live/fixture' in req.url:
            route.fulfill(json={'hero':'andrew','status':'active','sequence':1,
                               'captured':'2026-11-03T10:00:00Z','payload':deepcopy(payload)})
        else:route.fulfill(json={})
    page.route('**/api/**',api)
    page.goto('http://127.0.0.1:4297/?site_id=1&live_request=fixture')
    page.locator('.replay-seat').first.wait_for()
    assert page.locator('.replay-seat[data-seat="0"] > span').inner_text()=='1,000'
    assert page.locator('.table-bet[data-seat="0"]').inner_text()=='50'
    assert page.locator('.table-bet[data-seat="1"]').inner_text()=='100'
    assert page.locator('.replay-center > strong').inner_text()=='Pot 750'
    assert 'john wins 250' in page.locator('.hand-result').inner_text()
    assert 'Tournament chips' in page.locator('.live-title').inner_text()
    page.screenshot(path='artifacts/live-tournament-chips.png')
    # Conversion does not mutate decision/manual-control inputs, including a repeated render.
    page.evaluate("""async()=>{
      const {liveDisplaySnapshot}=await import('/live-amounts.js');
      const p={tournament:true,pot:.29,seats:[{stack:10,bet:.5}],manual:{pot_minor:29}};
      const a=liveDisplaySnapshot(p),b=liveDisplaySnapshot(p);
      if(a.pot!==29||b.pot!==29||p.pot!==.29||p.seats[0].stack!==10||a.manual!==p.manual)throw Error('Snapshot was mutated');
      const native={...a,amount_unit:'tournament_chips'};
      if(liveDisplaySnapshot(native)!==native||liveDisplaySnapshot(native).seats[0].stack!==1000)throw Error('Native chips rescaled twice');
    }""")
    # The same display must work while old and new workers coexist in a rollout.
    payload.update(amount_unit='tournament_chips',pot=750,big_blind=100)
    payload['seats'][0].update(stack=1000,bet=50)
    payload['seats'][1].update(stack=900,bet=100)
    payload['result']['winners'][0]['amount']=250
    page.reload();page.locator('.replay-seat').first.wait_for()
    assert page.locator('.replay-seat[data-seat="0"] > span').inner_text()=='1,000'
    assert page.locator('.table-bet[data-seat="1"]').inner_text()=='100'
    assert page.locator('.replay-center > strong').inner_text()=='Pot 750'
    assert 'john wins 250' in page.locator('.hand-result').inner_text()
    payload['tournament']=False
    payload.update(amount_unit='currency',pot=7.5,big_blind=1)
    payload['seats'][0].update(stack=10,bet=.5)
    payload['seats'][1].update(stack=9,bet=1)
    payload['result']['winners'][0]['amount']=2.5
    page.reload();page.locator('.replay-seat').first.wait_for()
    assert page.locator('.replay-seat[data-seat="0"] > span').inner_text()=='10.00'
    assert page.locator('.table-bet[data-seat="0"]').inner_text()=='0.50'
    assert page.locator('.replay-center > strong').inner_text()=='Pot 7.50'
    assert 'john wins 2.50' in page.locator('.hand-result').inner_text()
    assert 'Tournament chips' not in page.locator('.live-title').inner_text()
    assert not errors,errors
    assert not writes,writes
    browser.close()
print('Tournament chips, stacks, bets, pots and winnings display correctly; cash amounts and decision inputs are unchanged.')
