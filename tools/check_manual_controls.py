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
 assert not errors,errors
 browser.close()
 print('Manual switch, shortcuts, amount retention, submission and stale-state checks passed.')
