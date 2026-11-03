"""Tournament manual controls and table-move shutdown; all APIs are mocked."""
from copy import deepcopy
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page(viewport={'width':1300,'height':1000})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.route('**/manual-tournament-fixture',lambda r:r.fulfill(content_type='text/html',body='<link rel="stylesheet" href="/styles.css"><link rel="stylesheet" href="/fixes.css"><main id="controls"></main>'))
    page.goto('http://127.0.0.1:4298/manual-tournament-fixture')
    page.evaluate("""async()=>{
      const {ManualControls}=await import('/manual-controls.js');window.calls=[];
      window.controls=new ManualControls(document.querySelector('#controls'),'fixture',async(path,method,body)=>{
        calls.push({path,body});return path.endsWith('/manual')?{enabled:body.enabled}:{status:'queued'};
      });
      window.data={hero:'andrew',status:'active',captured:new Date().toISOString(),manual:{enabled:false},payload:{
        tournament:true,amount_unit:'tournament_chips',table_id:'42',table_name:'SNG test',game:'NLH',hand_id:'1',
        max_seats:2,pot:1200,big_blind:100,street:'Flop',board:[],seats:[],manual:{supported:true,enabled:false,
        amount_scale:1,request_id:'fixture',turn_key:'a'.repeat(64),actions:['fold','check','bet'],
        min_target_minor:100,max_target_minor:5000,pot_minor:1200,call_minor:0,hero_bet_minor:0,step_minor:100}}};
      controls.update(data);
    }""")
    assert not page.get_by_role('switch').is_checked()
    page.locator('.manual-track').click()
    page.evaluate('data.payload.manual.enabled=true;controls.update(data)')
    for label,value in [('33%','400'),('50%','600'),('75%','900'),('Pot','1200')]:
        page.get_by_role('button',name=label,exact=False).click()
        assert page.locator('[name=manual-amount]').input_value()==value
    page.keyboard.press('ArrowUp')
    assert page.locator('[name=manual-amount]').input_value()=='1300'
    page.keyboard.press('ArrowDown')
    assert page.locator('[name=manual-amount]').input_value()=='1200'
    page.locator('[name=manual-amount]').fill('600.5')
    assert page.get_by_role('button',name='Bet 600.5',exact=False).is_disabled()
    assert 'whole-chip' in page.locator('.manual-amount-error').inner_text()
    page.locator('[name=manual-amount]').fill('600')
    page.get_by_role('button',name='Bet 600',exact=False).click()
    assert page.evaluate('calls[1].body.amount')=='600'
    assert page.evaluate('calls[1].body.amount_unit')=='tournament_chips'
    page.evaluate("""data.manual.last_action=null;data.payload.street='Preflop';data.payload.seats=[{bet:100},{bet:200}];
      Object.assign(data.payload.manual,{turn_key:'b'.repeat(64),actions:['fold','call','raise'],min_target_minor:400,call_minor:100});controls.update(data);""")
    page.get_by_role('button',name='2.5BB',exact=False).click()
    assert page.locator('[name=manual-amount]').input_value()=='500'
    assert 'Call 100' in page.locator('.manual-actions').inner_text()
    page.screenshot(path='artifacts/tournament-manual-controls.png')
    page.evaluate("data.status='failed';data.error='The bot changed tables. Open a new live view.';data.manual.enabled=false;controls.update(data)")
    assert page.get_by_role('switch').is_disabled()
    assert page.locator('.manual-actions').count()==0
    assert 'new live view' in page.locator('.manual-note').inner_text()

    # Exercise the actual live-window app: a failed request stops polling even
    # when its last payload and timestamp still look fresh.
    response=page.evaluate('data')
    response.update(status='active',error=None,sequence=1)
    response['captured']='2026-11-03T12:00:00Z'
    response['payload']['seats']=[]
    count=[0];writes=[]
    def api(route):
        req=route.request;path=urlsplit(req.url).path
        if req.method!='GET':writes.append(req.url);route.abort();return
        if path.endswith('/me'):route.fulfill(json={'memberships':[{'id':14004,'role':'operator'}]})
        elif path.endswith('/sites'):route.fulfill(json={'items':[{'id':1,'name':'Evenbet','timezone':'Europe/Budapest'}]})
        elif '/tables/live/fixture' in path:count[0]+=1;route.fulfill(json=deepcopy(response))
        else:route.fulfill(json={})
    page.route('**/api/**',api)
    page.goto('http://127.0.0.1:4298/?site_id=1&live_request=fixture')
    page.locator('.live-title').wait_for()
    response.update(status='failed',error='The bot changed tables. Open a new live view.')
    page.wait_for_function("document.querySelector('#live-status').textContent.includes('new live view')")
    stopped=count[0];page.wait_for_timeout(1200)
    assert count[0]==stopped and not writes
    assert page.get_by_role('switch').is_disabled()
    assert not errors,errors
    browser.close()
print('Tournament manual chip inputs, shortcuts, queued amount and table-move shutdown passed. No poker actions sent.')
