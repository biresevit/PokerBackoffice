"""Exercise Monitoring charts and filtered paging with synthetic events; no live writes."""
import json
import sys
from collections import Counter
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.parse import parse_qs,urlsplit

from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'api'))
from backoffice.monitoring import Monitoring
from backoffice.store import Store,Context
from backoffice.app import json_default

NOW=datetime(2026,11,24,12,tzinfo=timezone.utc)
events=[dict(machine=5 if i%2==0 else 1030,kind='sit_out',at=NOW.replace(tzinfo=None)-timedelta(seconds=60+i*30),
             username=f'Sample{i:04}',table_id='sample',table_name='Sample table') for i in range(1971)]

class Db:
    def rows(self,sql,*args):
        if 'MachineAssignment' in sql:return [{'id':5,'name':'Sample PC 5'},{'id':1030,'name':'Sample PC 1030'}]
        if 'DecisionMetric' in sql:
            return [dict(machine=5,hour=NOW.replace(tzinfo=None)-timedelta(hours=hour),street=street,decisions=10,
                total_ms=street*1000,max_ms=9999999,Under250=10,Under500=0,Under1000=0,Under2000=0,Under5000=0,Over5000=0)
                for street in range(1,5) for hour in (1,2)]
        if 'ActionTimeout' in sql:
            rows=[e for e in events if args[1]<=e['at']<args[2] and ('t.MachineId=%s' not in sql or e['machine']==args[3])]
            if 'COUNT_BIG' in sql:
                counts=Counter((e['machine'],e['kind'],e['at'].replace(second=0,microsecond=0)) for e in rows)
                return [dict(machine=m,kind=k,at=t,count=n) for (m,k,t),n in counts.items()]
            return rows[args[-2]:args[-2]+args[-1]]
        raise AssertionError(sql)

HTML='''<!doctype html><meta charset="utf-8"><main id="app"></main><script type="module">
import {installMonitoring} from '/monitoring-ui.js';
const $=s=>document.querySelector(s),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state={generation:1,customer:{id:3},site:{id:1006}};
const h={$ ,esc,state,render:(g,d,html)=>{if(g!==state.generation)return false;$('#app').innerHTML=html;return true;},
siteApi:async path=>{const r=await fetch('/api/'+path);if(!r.ok)throw Error('API failed');return r.json();},
table:(headers,rows)=>`<table><thead><tr>${headers.map(x=>`<th>${x}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table>`,
card:(title,body)=>`<section class="card"><h2>${title}</h2>${body}</section>`,stats:()=>'',empty:t=>t,toast:t=>{throw Error(t);},
select:(label,name,value,options)=>`<label>${label}<select name="${name}">${options.map(([v,t])=>`<option value="${v}" ${String(v)===String(value)?'selected':''}>${t}</option>`).join('')}</select></label>`};
let ui;h.navigate=async()=>{state.generation++;await ui.page(state.generation);};ui=installMonitoring(h);await ui.page(1);
</script>'''

def main():
    requests=[]
    def route(request):
        path=urlsplit(request.request.url)
        if path.path=='/':return request.fulfill(body=HTML,content_type='text/html')
        if path.path=='/monitoring-ui.js':return request.fulfill(body=(ROOT/'frontend/monitoring-ui.js').read_bytes(),content_type='application/javascript')
        query={k:v[0] for k,v in parse_qs(path.query).items()};requests.append(query)
        store=Store(Db(),Context(3,'local','synthetic','viewer'));store.site=lambda sid:{'timezone':'Europe/Rome'}
        result=Monitoring(store).get(1006,query)
        request.fulfill(body=json.dumps(result,default=json_default),content_type='application/json')
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(timezone_id='Europe/Budapest',viewport={'width':1440,'height':1000})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.clock.set_fixed_time(NOW)
        page.route('**/*',route)
        page.goto('http://monitoring.test/',wait_until='networkidle')
        page.locator('#missed-rows tbody tr').nth(19).wait_for()
        assert page.locator('#missed-rows tbody tr').count()==20
        assert page.locator('.monitor-grid .max').count()==0
        assert page.locator('.monitor-grid svg').count()==4
        assert not any('9999999' in t for t in page.locator('.monitor-grid').all_text_contents())
        assert page.get_by_role('img',name='Missed actions per day',exact=True).count()==1
        assert page.locator('.monitor-readout').count()==6
        count_before_hover=len(requests)
        first=page.locator('.monitor-grid svg').first
        point=first.locator('circle.avg').first.bounding_box()
        page.mouse.move(point['x']+point['width']/2,point['y']+point['height']/2)
        readout=first.locator('xpath=following-sibling::div[contains(@class,"monitor-readout")]')
        assert '11:00' in readout.inner_text() and 'Average: 100 ms' in readout.inner_text()
        first.focus();page.keyboard.press('End')
        assert '12:00' in readout.inner_text()
        for name in ('Missed actions per hour','Missed actions per day'):
            svg=page.get_by_role('img',name=name,exact=True)
            bar=svg.locator('rect.missed').first
            expected=bar.locator('title').text_content().split(': ')[-1].split()[0]
            bar.scroll_into_view_if_needed()
            box=bar.bounding_box()
            page.mouse.move(box['x']+box['width']/2,box['y']+max(1,box['height']/2))
            text=svg.locator('xpath=following-sibling::div[contains(@class,"monitor-readout")]').inner_text()
            assert '2026' in text and f'Missed actions: {int(expected):,}' in text
        assert len(requests)==count_before_hover,'Hover must not request new data'
        page.click('#missed-next');page.wait_for_function("document.querySelector('#missed-rows tbody td:nth-child(2)').textContent==='Sample0020'")
        assert requests[-1]['page']=='2' and requests[-1]['page_size']=='20'
        assert requests[-1]['from']==requests[0]['from'] and requests[-1]['to']==requests[0]['to']
        page.select_option('[name=missed_page_size]','50');page.wait_for_function("document.querySelectorAll('#missed-rows tbody tr').length===50")
        assert requests[-1]['page']=='1'
        page.select_option('[name=machine]','5');page.get_by_role('button',name='Apply filters',exact=True).click()
        page.wait_for_function("[...document.querySelectorAll('#missed-rows tbody tr')].every(r=>r.textContent.includes('Sample PC 5'))")
        assert requests[-1]['machine']=='5' and requests[-1]['page']=='1'
        page.click('#missed-next');page.wait_for_function("document.querySelector('#missed-rows tbody td:nth-child(2)').textContent==='Sample0100'")
        assert requests[-1]['machine']=='5' and requests[-1]['page']=='2'
        page.select_option('[name=missed_page_size]','100');page.wait_for_function("document.querySelectorAll('#missed-rows tbody tr').length===100")
        assert requests[-1]['page']=='1'
        page.click('#monitor-reset');page.wait_for_function("document.querySelectorAll('#missed-rows tbody tr').length===20")
        assert requests[-1]['machine']=='all' and requests[-1]['page_size']=='20'
        assert not errors,errors
        browser.close()
    print('PASS: average-only charts, time/value hover and keyboard readouts, daily chart, paging and filters.')

if __name__=='__main__':main()
