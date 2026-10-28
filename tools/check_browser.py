"""Smoke-test real local preview without changing customer data."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"artifacts"
OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch()
    page=browser.new_page(viewport={"width":1440,"height":1000})
    errors=[]
    page.on("pageerror",lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:4280")
    page.get_by_role("heading",name="Overview",exact=True).wait_for()
    board_colors=page.evaluate("""() => {
      const root=document.createElement('div');
      root.className='live-felt';
      root.style.display='none';
      root.innerHTML='<div class="replay-center"><div class="cards board"><i class="playing-card red"><span>♦</span></i><i class="playing-card black"><span>♠</span></i></div><span class="street">Complete</span></div>';
      document.body.appendChild(root);
      root.style.display='block';
      const colors=[...root.querySelectorAll('.playing-card span')].map(x=>getComputedStyle(x).color);
      root.remove();
      return colors;
    }""")
    assert board_colors==['rgb(201, 28, 39)','rgb(32, 37, 34)'],board_colors
    for name,title in [("accounts","Accounts"),("schedule","Weekly schedule"),("stakes","Stakes"),("machines","Machines"),("tasks","Tasks"),("sessions","Sessions"),("tables","Live tables"),("histories","Hand histories"),("simulation","Schedule simulator")]:
        page.goto("http://127.0.0.1:4280/#"+name)
        page.get_by_role("heading",name=title,exact=True,level=1).wait_for()
        page.wait_for_timeout(500)
        assert not page.locator(".notice.error").count(),page.locator(".notice.error").all_text_contents()
        if name=="accounts":
            page.get_by_role("row").filter(has_text="monica").get_by_role("button",name="Details").click()
            assert page.locator('[name="session_min_minutes"]').input_value()=="60"
            assert page.locator('[name="session_max_minutes"]').input_value()=="240"
            page.get_by_role("button",name="Cancel",exact=True).click()
            page.get_by_role("button",name="Import CSV",exact=True).click()
            page.locator('#csv-file').set_input_files({"name":"accounts.csv","mimeType":"text/csv","buffer":b"username,profile\nmonica,Strong Balanced"})
            page.get_by_role("button",name="Preview changes").click()
            page.locator('#csv-preview').get_by_role('cell',name='unchanged',exact=True).wait_for()
            page.get_by_role("button",name="Cancel",exact=True).click()
        if name=="schedule":
            assert page.get_by_role("button",name="Save schedule",exact=True).count()==0
            page.get_by_role("button",name="+ Add window",exact=True).click()
            assert page.locator('#dialog [name="start"]').input_value()=="17:00"
            assert page.locator('#dialog [name="end"]').input_value()=="18:00"
            assert page.locator('#dialog [name="weekdays"]').count()==7
            assert page.locator('#dialog [name="weekdays"]:checked').count()==1
            page.get_by_role("button",name="Every day",exact=True).click()
            assert page.locator('#dialog [name="weekdays"]:checked').count()==7
            page.get_by_role("button",name="Done",exact=True).click()
        if name=="tasks":
            assert page.locator('[name="machine"]').count()==1
            assert page.locator('[name="bot"]').count()==1
            assert page.locator('[name="kind"] option').all_text_contents()==['All task types','Join table','Leave table','Scan lobby']
        if name=="sessions":
            assert page.locator('[name="from"]').input_value()!=""
            assert page.locator('[name="to"]').input_value()!=""
        if name=="histories":
            assert page.locator('[name="min_blind"]').input_value()!=""
            assert page.locator('[name="max_blind"]').input_value()!=""
            assert page.locator('[name="sort"]').input_value()=="winnings_desc"
            assert page.locator('[name="page_size"]').input_value()=="20"
            page.locator('#hh-status').filter(has_text='Loaded').wait_for(timeout=30000)
            page.locator('[name="game"]').select_option('PLO4')
            with page.expect_response(lambda response:'/histories?' in response.url):
                page.locator('#load-hh').click()
            page.locator('#load-hh:not([disabled])').wait_for()
            page.locator('#hh-status').filter(has_text='Loaded').wait_for(timeout=30000)
            assert page.locator('[data-replay]').count()>0
            assert page.locator('#select-page').count()==0
            page.locator('#select-all').check()
            assert page.locator('[data-hand]:not(:checked)').count()==0
            assert 'Select all (' in page.locator('.history-actions').inner_text()
            if page.locator('#hh-next').is_enabled():
                page.locator('#hh-next').click()
                page.locator('.pagination span').filter(has_text='Page 2 of').wait_for()
                assert page.locator('[data-hand]:not(:checked)').count()==0
                page.locator('#hh-prev').click()
                page.locator('.pagination span').filter(has_text='Page 1 of').wait_for()
            page.evaluate("""() => { const real=window.fetch; window.fetch=(url,options) => String(url).includes('histories/download') ? new Promise(resolve=>setTimeout(()=>resolve(new Response(new Blob(['PK'],{type:'application/zip'}),{status:200})),600)) : real(url,options); }""")
            page.locator('#download-hh').click()
            assert page.locator('#download-hh').is_disabled()
            assert page.locator('#download-hh .spinner').count()==1
            assert 'Preparing the selected hand histories' in page.locator('#hh-status').inner_text()
            page.locator('#download-hh:not([disabled])').wait_for()
            assert 'Download ready' in page.locator('#hh-status').inner_text()
            page.locator('[data-replay]').first.click()
            page.locator('.poker-replay').wait_for(timeout=30000)
            assert page.locator('.poker-replay').count()==1
            replay_bounds=page.evaluate("""() => { const viewport=document.querySelector('.replay-dialog .dialog-content').getBoundingClientRect(); const cards=[...document.querySelectorAll('.replay-felt .seat-cards')].map(x=>x.getBoundingClientRect().top); return {viewportTop:viewport.top,topCard:Math.min(...cards)}; }""")
            assert replay_bounds['topCard']>=replay_bounds['viewportTop'],replay_bounds
            page.set_viewport_size({"width":390,"height":844})
            mobile_replay_bounds=page.evaluate("""() => { const viewport=document.querySelector('.replay-dialog .dialog-content').getBoundingClientRect(); const cards=[...document.querySelectorAll('.replay-felt .seat-cards')].map(x=>x.getBoundingClientRect().top); return {viewportTop:viewport.top,topCard:Math.min(...cards)}; }""")
            assert mobile_replay_bounds['topCard']>=mobile_replay_bounds['viewportTop'],mobile_replay_bounds
            page.set_viewport_size({"width":1440,"height":1000})
            assert page.locator('.seat-cards .playing-card:not(.back)').count()>0
            back_counts=page.locator('.replay-seat').evaluate_all("els=>els.filter(e=>e.querySelector('.playing-card.back')).map(e=>e.querySelectorAll('.playing-card.back').length)")
            assert back_counts and all(count==4 for count in back_counts),back_counts
            overlaps=page.evaluate("""() => [...document.querySelectorAll('.replay-felt .table-bet')].some(b => { const r=b.getBoundingClientRect(),seat=document.querySelector(`.replay-felt .replay-seat[data-seat="${b.dataset.seat}"]`); return [...seat.querySelectorAll('.playing-card')].some(c => { const q=c.getBoundingClientRect(); return r.left<q.right&&r.right>q.left&&r.top<q.bottom&&r.bottom>q.top; }); })""")
            assert not overlaps
            assert page.locator('.dealer-button').count()==1
            initial_count=page.locator('#replay-count').inner_text()
            page.keyboard.press('ArrowRight')
            assert page.locator('#replay-count').inner_text()!=initial_count
            page.locator('.replay-action-bubble').wait_for()
            page.keyboard.press('ArrowLeft')
            assert page.locator('#replay-count').inner_text()==initial_count
            page.keyboard.press('ArrowRight')
            assert page.locator('.replay-action-bubble').evaluate("e=>getComputedStyle(e).opacity")=='1'
            page.wait_for_timeout(2200)
            assert page.locator('.replay-action-bubble').evaluate("e=>getComputedStyle(e).opacity")=='0'
            replay_height=page.locator('#replay-table').evaluate("e=>e.getBoundingClientRect().height")
            dialog_height=page.locator('.replay-dialog').evaluate("e=>e.getBoundingClientRect().height")
            while page.locator('#replay-next').is_enabled():
                page.locator('#replay-next').click()
            assert page.locator('.replay-step-label').count()==0
            assert 'wins' in page.locator('#replay-step-status').inner_text().lower()
            assert page.locator('#replay-table').evaluate("e=>e.getBoundingClientRect().height")==replay_height
            assert page.locator('.replay-dialog').evaluate("e=>e.getBoundingClientRect().height")==dialog_height
            page.locator('#close-dialog').click()
            page.get_by_role('tab',name='Bot winnings').click()
            page.get_by_role('heading',name='Bot winnings',exact=True).wait_for(timeout=30000)
            assert page.locator('#hh-hands-panel').is_hidden()
            page.get_by_role('tab',name='Hand histories').click()
            assert page.locator('#hh-winnings-panel').is_hidden()
        if name=="tables":
            assert page.locator('[name="live-game"] option').all_text_contents()==['All games','NLH','PLO4','PLO5']
            assert page.locator('[name="live-type"] option').all_text_contents()==['All types','Ring','SNG','MTT']
    page.get_by_role("button",name="Run simulation").click()
    page.get_by_role("heading",name="What happens, and when").wait_for(timeout=30000)
    assert page.locator("#event-list tbody tr").count()>36
    assert "Invalid Date" not in page.locator("#sim-output").inner_text()
    page.screenshot(path=str(OUT/"simulation-desktop.png"),full_page=True)
    page.set_viewport_size({"width":390,"height":844})
    page.wait_for_timeout(400)
    page.get_by_role('button',name='Open navigation').click()
    page.locator('.sidebar.open').wait_for()
    page.locator('[data-page="accounts"]').click()
    page.get_by_role('heading',name='Accounts',exact=True).wait_for()
    assert not page.locator('.sidebar.open').count()
    page.goto('http://127.0.0.1:4280/#simulation')
    page.get_by_role('button',name='Run simulation').click()
    page.get_by_role('heading',name='What happens, and when').wait_for()
    page.wait_for_timeout(400)
    page.screenshot(path=str(OUT/"simulation-mobile.png"),full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"),"Mobile page overflows"
    print(json.dumps({"browser_errors":errors,"timeline_rows":page.locator('#event-list tbody tr').count()}))
    assert not errors
    browser.close()
