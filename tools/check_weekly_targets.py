"""Browser checks for precise, readable weekly targets; uses mocked saves only."""
import json
from playwright.sync_api import sync_playwright
windows=[
 {'weekday':0,'start_minute':0,'end_minute':180,'target':5},
 {'weekday':0,'start_minute':550,'end_minute':655,'target':15},
 {'weekday':0,'start_minute':1320,'end_minute':1440,'target':30},
 {'weekday':1,'start_minute':0,'end_minute':60,'target':0},
 {'weekday':2,'start_minute':601,'end_minute':616,'target':11},
 {'weekday':3,'start_minute':480,'end_minute':1440,'target':24},
 {'weekday':4,'start_minute':540,'end_minute':1080,'target':18},
 {'weekday':5,'start_minute':480,'end_minute':1440,'target':27},
 {'weekday':6,'start_minute':480,'end_minute':1440,'target':30},
]
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True)
 page=browser.new_page(viewport={'width':1440,'height':1080})
 errors=[];writes=[]
 page.on('pageerror',lambda e:errors.append(str(e)))
 def route_api(route):
  request=route.request
  if request.method!='GET':
   if '/sites/1/schedule' in request.url:
    writes.append(request.post_data_json);route.fulfill(json={'version':len(writes)+1});return
   route.abort();return
  if '/sites/1/schedule?' in request.url:route.fulfill(json={'enabled':True,'timezone':'Europe/Budapest','version':1,'windows':windows})
  else:route.continue_()
 page.route('**/api/**',route_api)
 page.goto('http://127.0.0.1:4296/backoffice/?site_id=1#schedule')
 page.locator('.weekly-target-chart').wait_for(timeout=30000)
 assert page.locator('.weekly-time-tick').count()==13
 assert page.locator('.weekly-time-tick.first').inner_text()=='00:00'
 assert page.locator('.weekly-time-tick.last').inner_text()=='24:00'
 axes=page.locator('.weekly-axis').bounding_box();track=page.locator('.day-track').first.bounding_box()
 assert abs(axes['x']-track['x'])<1 and abs(axes['width']-track['width'])<1
 low=page.locator('[data-window="0"]');high=page.locator('[data-window="2"]')
 assert low.evaluate('(e)=>getComputedStyle(e).backgroundColor')!=high.evaluate('(e)=>getComputedStyle(e).backgroundColor')
 ratios=page.locator('.weekly-targets .block').evaluate_all("""elements=>{
  const luminance=s=>{const c=s.match(/\d+/g).slice(0,3).map(v=>{v=Number(v)/255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;});return c[0]*.2126+c[1]*.7152+c[2]*.0722;};
  return elements.map(e=>{const s=getComputedStyle(e),a=luminance(s.color),b=luminance(s.backgroundColor);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);});
 }""")
 assert min(ratios)>=4.5,ratios
 exact=page.get_by_role('button',name='Monday: 09:10–10:55, 15 scheduled entries',exact=True)
 exact.hover();assert '09:10–10:55' in page.locator('.weekly-selection-text').inner_text()
 position=exact.bounding_box()
 assert abs((position['x']-track['x'])-track['width']*550/1440)<2
 exact.click();high.hover();page.get_by_role('button',name='Edit window',exact=True).hover()
 assert '09:10'+chr(0x2013)+'10:55' in page.locator('.weekly-selection-text').inner_text()
 page.get_by_role('button',name='Edit window',exact=True).click()
 assert page.get_by_role('heading',name='Edit schedule window',exact=True).is_visible()
 assert page.locator('#dialog [name=start]').input_value()=='09:10'
 assert page.locator('#dialog [name=end]').input_value()=='10:55'
 assert page.locator('#dialog [name=target]').input_value()=='15'
 assert page.locator('#dialog [name=weekdays]:checked').evaluate_all('(els)=>els.map(e=>e.value)')==['0']
 page.get_by_role('button',name='Cancel',exact=True).click()
 assert page.locator('#windows').count()==0
 assert page.get_by_role('heading',name='Ring schedule windows',exact=True).count()==0
 toolbar=page.locator('.weekly-edit-toolbar').bounding_box()
 assert toolbar['y']<page.locator('.weekly-target-chart').bounding_box()['y']
 exact.dblclick()
 assert page.locator('#dialog [name=target]').input_value()=='15'
 page.get_by_role('button',name='Cancel',exact=True).click()
 page.locator('#week').locator('..').scroll_into_view_if_needed()
 page.screenshot(path='artifacts/weekly-targets-desktop.png')
 page.set_viewport_size({'width':390,'height':844})
 page.wait_for_timeout(300)
 page.locator('.weekly-target-scroll').scroll_into_view_if_needed()
 assert page.locator('.weekly-target-scroll').evaluate('(e)=>e.scrollWidth>e.clientWidth')
 assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
 page.locator('[data-window="4"]').focus()
 assert page.locator('.day-label').first.bounding_box()['x']>=page.locator('.weekly-target-scroll').bounding_box()['x']-1
 assert '10:01–10:16' in page.locator('.weekly-selection-text').inner_text()
 page.screenshot(path='artifacts/weekly-targets-mobile.png')
 html=page.evaluate("""async()=>{const {weeklyTargetChart}=await import('/weekly-targets.js');return weeklyTargetChart([{weekday:0,start_minute:0,end_minute:60,target:0}],['Monday'],'Europe/Budapest');}""")
 assert 'Peak: 0' in html and 'NaN' not in html and 'Infinity' not in html
 # Saving replaces the chosen window instead of appending a duplicate.
 page.locator('[data-window="4"]').dblclick()
 page.locator('#dialog [name=target]').fill('12')
 page.get_by_role('button',name='Save changes',exact=True).click()
 page.wait_for_function("!document.querySelector('#dialog').open")
 assert len(writes)==1 and len(writes[-1]['windows'])==len(windows)
 assert [w for w in writes[-1]['windows'] if w['weekday']==2]==[dict(windows[4],target=12)]
 page.locator('[data-window="8"]').dblclick()
 page.get_by_role('button',name='Remove window',exact=True).click()
 page.wait_for_function("!document.querySelector('#dialog').open")
 assert len(writes)==2 and len(writes[-1]['windows'])==len(windows)-1
 page.get_by_role('button',name='+ Add window',exact=True).click()
 page.get_by_role('button',name='Clear',exact=True).click()
 page.locator('#dialog [name=weekdays][value="2"]').locator('..').click()
 page.locator('#dialog [name=start]').fill('22:00')
 page.locator('#dialog [name=end]').fill('24:00')
 page.locator('#dialog [name=target]').fill('0')
 page.get_by_role('button',name='Add and save',exact=True).click()
 page.wait_for_function("document.querySelectorAll('[data-window]').length===9")
 assert len(writes)==3 and writes[-1]['windows'][-1]=={'weekday':2,'start_minute':1320,'end_minute':1440,'target':0}
 assert page.locator('#dialog').is_visible()
 page.get_by_role('button',name='Done',exact=True).click()
 assert not errors,errors
 browser.close()
 print('Two-hour axis, exact boundaries, peak colors, contrast, selection, double-click/edit/save/remove, add through midnight, zero targets and mobile scrolling passed. All saves were mocked.')
