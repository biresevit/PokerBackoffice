"""Browser regression for live-table controls; all actions use a local mock API."""
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True)
 page=browser.new_page(viewport={"width":1200,"height":850})
 errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.route('**/manual-fixture',lambda r:r.fulfill(content_type='text/html',body='<link rel="stylesheet" href="/styles.css"><link rel="stylesheet" href="/fixes.css"><main id="controls"></main>'))
 page.goto('http://127.0.0.1:4294/manual-fixture')
 page.evaluate("""async()=>{
  const {ManualControls}=await import('/manual-controls.js');window.calls=[];
  window.controls=new ManualControls(document.querySelector('#controls'),'request',async(path,method,body)=>{calls.push({path,body});return path.endsWith('/manual')?{enabled:body.enabled}:{status:'queued'};});
  window.data={hero:'kate',captured:new Date().toISOString(),manual:{enabled:false},payload:{manual:{supported:true,enabled:false,request_id:'request',turn_key:'a'.repeat(64),actions:['fold','check','bet'],min_target_minor:200,max_target_minor:40000,pot_minor:12000,call_minor:0,hero_bet_minor:0,step_minor:200}}};
  controls.update(data);
 }""")
 assert not page.get_by_role('switch').is_checked()
 page.get_by_role('switch').click()
 page.wait_for_function("calls.length===1")
 page.evaluate("data.manual.enabled=true;data.payload.manual.enabled=true;controls.update(data)")
 for label,value in [('1/3','40.00'),('2/3','80.00'),('3/4','90.00'),('Pot size','120.00')]:
  page.get_by_role('button',name=label,exact=True).click()
  assert page.locator('[name=manual-amount]').input_value()==value
 page.evaluate("data.payload.seats=[{bet:1},{bet:2}];controls.update(data)")
 page.get_by_role('button',name='Pot size',exact=True).click()
 assert page.locator('[name=manual-amount]').input_value()=='123.00'
 page.evaluate("data.payload.seats=[];controls.update(data)")
 page.get_by_role('button',name='Pot size',exact=True).click()
 page.get_by_role('button',name='Increase bet').click()
 assert page.locator('[name=manual-amount]').input_value()=='122.00'
 page.get_by_role('button',name='Decrease bet').click()
 page.locator('[name=manual-amount]').fill('125.50')
 page.evaluate('controls.update(data)')
 assert page.locator('[name=manual-amount]').input_value()=='125.50'
 page.screenshot(path='artifacts/manual-controls.png')
 page.get_by_role('button',name='Bet 125.50',exact=True).click()
 page.wait_for_function('calls.length===2')
 assert page.evaluate('calls[1].body.amount')=='125.50'
 assert page.get_by_role('button',name='Fold',exact=True).count()==0
 page.evaluate("data.captured=new Date(Date.now()-10000).toISOString();controls.update(data)")
 assert page.get_by_role('switch').is_disabled()
 page.evaluate("controls.disconnected()")
 assert page.get_by_role('button',name='Fold',exact=True).count()==0
 # A size outside the table's limits is stopped on the page, with the limits shown.
 page.evaluate("data.captured=new Date().toISOString();data.payload.manual.turn_key='b'.repeat(64);data.manual.last_action=null;controls.update(data)")
 page.locator('[name=manual-amount]').fill('1.00')
 assert page.get_by_role('button',name='Bet 1.00',exact=True).is_disabled()
 assert 'between 2.00 and 400.00' in page.locator('.manual-amount-error').inner_text()
 page.locator('[name=manual-amount]').fill('abc')
 assert page.get_by_role('button',name='Bet abc',exact=True).is_disabled()
 # A decimal comma is accepted and sent as a decimal point.
 page.locator('[name=manual-amount]').fill('3,5')
 page.get_by_role('button',name='Bet 3,5',exact=True).click()
 page.wait_for_function('calls.length===3')
 assert page.evaluate('calls[2].body.amount')=='3.50'
 # A refused action is shown as a problem and the turn's buttons come back for a new choice.
 page.evaluate("data.manual.last_action={turn_key:'b'.repeat(64),status:'failed',detail:'The table refused this action: Bad amount. Choose again.'};controls.update(data)")
 assert page.locator('.manual-note.manual-problem').inner_text().startswith('The table refused')
 assert page.get_by_role('button',name='Fold',exact=True).count()==1
 # Sit out next hand, then I'm back once the hero is away.
 page.evaluate("data.payload.manual.table_commands=true;controls.update(data)")
 page.get_by_role('button',name='Sit out next hand',exact=True).click()
 page.wait_for_function('calls.length===4')
 assert page.evaluate('calls[3].body')=={'action':'sit_out'}
 assert page.get_by_role('button',name='Sit out next hand',exact=True).count()==0
 page.evaluate("Object.assign(data.payload.manual,{away:true,turn_key:null,actions:[]});data.manual.last_command={action:'sit_out',status:'sent',detail:'',age:40};controls.update(data)")
 assert 'Press I’m back' in page.locator('.manual-note').inner_text()
 page.get_by_role('button',name='I’m back',exact=True).click()
 page.wait_for_function('calls.length===5')
 assert page.evaluate('calls[4].body')=={'action':'sit_in'}
 # With manual control off the bot returns by itself, so there is no button.
 page.evaluate("data.manual.enabled=false;data.manual.last_command=null;controls.update(data)")
 assert 'automatically' in page.locator('.manual-note').inner_text()
 assert page.get_by_role('button',name='I’m back',exact=True).count()==0
 page.evaluate("data.manual.enabled=true;data.manual.last_command={action:'sit_in',status:'failed',detail:'The table refused: not now',age:2};controls.update(data)")
 assert page.locator('.manual-note.manual-problem').inner_text()=='The table refused: not now'
 page.screenshot(path='artifacts/manual-controls-away.png')
 assert not errors,errors
 browser.close()
 print('Manual switch, shortcuts, amount retention, validation, refusal, sit-out and stale-state checks passed.')
