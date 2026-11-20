"""Local end-to-end QA. Live mode explicitly calls the model with read-only site data."""
import argparse
import json
import os
import secrets
import subprocess
import sqlite3
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
PY=ROOT/'diagnostics/.venv/Scripts/python.exe'
OUT=ROOT/'artifacts/diagnostics'
OUT.mkdir(parents=True,exist_ok=True)
parser=argparse.ArgumentParser()
parser.add_argument('--mode',choices=('recorded','live'),default='recorded')
parser.add_argument('--port',type=int,default=4380)
parser.add_argument('--worker-port',type=int,default=4410)
options=parser.parse_args()
mode=options.mode
preview=f'http://127.0.0.1:{options.port}'
worker=f'http://127.0.0.1:{options.worker_port}'
if mode=='live' and not os.getenv('OPENAI_API_KEY'):
    raise SystemExit('Configure OPENAI_API_KEY locally before running --mode live')
history_path=OUT/f'browser-history-{time.time_ns()}.sqlite3'
env=dict(os.environ,POKERFILL_DIAGNOSTICS_TOKEN=secrets.token_urlsafe(48),
         POKERFILL_DIAGNOSTICS_MODE=mode,POKERFILL_DIAGNOSTICS_URL=worker,
         POKERFILL_DIAGNOSTICS_HISTORY=str(history_path))
processes=[]


def ready(url):
    for _ in range(100):
        try:
            with urllib.request.urlopen(url,timeout=2) as r:
                if r.status==200:return
        except OSError:time.sleep(.2)
    raise RuntimeError('Local server did not become ready')


def completed(page):
    page.wait_for_function("/^(completed|failed)/.test(document.querySelector('.diagnosis-turn:last-child .diagnosis-turn-status')?.textContent || '')",timeout=300000)
    latest=page.locator('.diagnosis-turn').last
    assert latest.locator('.diagnosis-turn-status').inner_text().startswith('completed'),latest.inner_text()
    latest.locator('.diagnosis-summary').wait_for()
    if mode=='recorded':
        followup='Recorded-data follow-up:' in latest.locator('.diagnosis-summary').inner_text()
        latest.get_by_role('heading',name='Earlier diagnosis context' if followup else 'Stale lobby evidence').wait_for()


try:
    with (OUT/f'{mode}-browser-server.log').open('w',encoding='utf-8') as log:
        for args in ([str(PY),'-m','uvicorn','diagnostics.service:app','--host','127.0.0.1','--port',str(options.worker_port),'--no-access-log'],
                     [str(PY),'tools/preview.py','--port',str(options.port),'--customer-id','14004']):
            processes.append(subprocess.Popen(args,cwd=ROOT,env=env,stdout=log,stderr=log))
        ready(worker+'/health');ready(preview+'/backoffice')
        with sync_playwright() as p:
            browser=p.chromium.launch()
            page=browser.new_page(viewport={'width':1440,'height':1080})
            errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(preview+'/backoffice#diagnostics')
            page.get_by_role('heading',name='AI diagnosis',exact=True).wait_for(timeout=30000)
            page.get_by_text('Recorded demonstration · no live data' if mode=='recorded' else 'Live diagnosis',exact=True).wait_for()
            for platform in ('EvenBet','BluffPoker'):
                options=page.locator('#site option').evaluate_all('(xs)=>xs.map(x=>({id:x.value,text:x.textContent}))')
                choice=next(x for x in options if platform.lower() in x['text'].lower())
                page.select_option('#site',choice['id'])
                page.get_by_role('heading',name='What would you like to investigate?').wait_for()
                page.fill('#diagnosis-prompt',f'Why are fewer ring entries running than scheduled on {platform}?')
                page.click('#diagnosis-submit')
                completed(page)
                assert page.locator('#diagnosis-answer img').count()==0
                if mode=='recorded':
                    page.get_by_role('button',name='Ask follow-up',exact=True).wait_for()
                    page.fill('#diagnosis-prompt','Why did you call that probable?')
                    page.click('#diagnosis-submit');page.locator('.diagnosis-turn').nth(1).wait_for();completed(page)
                    assert page.locator('.diagnosis-turn').count()==2
                    assert 'previous questions and answers were included' in page.locator('.diagnosis-summary').last.inner_text()
                    assert page.locator('[data-diagnosis]').count()==1
                page.reload()
                page.get_by_role('heading',name='Your requests').wait_for()
                # Site selection is not persisted in this app; select the same site after reload.
                page.select_option('#site',choice['id'])
                page.locator('[data-diagnosis]').first.wait_for(timeout=30000)
                page.locator('[data-diagnosis]').first.click()
                completed(page)
                if mode=='recorded':
                    assert page.locator('.diagnosis-turn').count()==2
                    older=page.locator('.diagnosis-turn').first
                    older.get_by_text('Evidence for this answer',exact=True).click()
                    older.locator('[data-load-evidence]').click()
                    older.locator('.diagnosis-evidence details').first.wait_for()
                    older.locator('.diagnosis-evidence details').first.locator('summary').click()
                    older.locator('.diagnosis-evidence pre').first.wait_for()
                    older.get_by_text('Evidence for this answer',exact=True).click()
                page.screenshot(path=str(OUT/f'{mode}-{platform.lower()}-desktop.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            page.wait_for_timeout(350)  # Let the existing mobile navigation transition finish.
            page.screenshot(path=str(OUT/f'{mode}-diagnosis-mobile.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'), 'Mobile horizontal overflow'
            assert page.locator('.sidebar').bounding_box()['x']<0, 'Mobile navigation must be closed'
            if mode=='recorded':
                page.click('#diagnosis-new')
                assert page.get_by_role('button',name='Investigate',exact=True).is_enabled()
                page.fill('#diagnosis-prompt','Why fewer entries? <img src=x onerror=alert(1)>')
                page.click('#diagnosis-submit')
                page.get_by_role('heading',name='Why fewer entries? <img src=x onerror=alert(1)>',exact=True).wait_for()
                assert page.locator('#diagnosis-answer img').count()==0
                completed(page)
                assert page.locator('.diagnosis-turn').count()==1
                assert page.locator('[data-diagnosis]').count()==2
            assert not errors,errors
            browser.close()
            if mode=='live':
                with sqlite3.connect(history_path) as db:
                    results=[json.loads(r[0]) for r in db.execute("SELECT result FROM investigations WHERE status='completed'")]
                assert len(results)==2
                for result in results:
                    assert result['mode']=='live' and result['usage']['total_tokens']>0
                    ids={e['id'] for e in result['evidence']}
                    assert all(f['evidence_ids'] and set(f['evidence_ids'])<=ids for f in result['report']['findings'])
                (OUT/'live-browser-results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
                print('Model tokens used:',sum(r['usage']['total_tokens'] for r in results))
            print(f'PASS ({mode}): EvenBet and BluffPoker prompt, answer, private history reload, desktop and mobile')
finally:
    for process in reversed(processes):
        process.terminate()
        try:process.wait(timeout=8)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
