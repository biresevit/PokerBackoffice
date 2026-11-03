"""Browser check with mocked requests and a fake downloadable ZIP. No real log requests."""
from io import BytesIO
from pathlib import Path
import zipfile
from playwright.sync_api import sync_playwright,expect

archive=BytesIO()
with zipfile.ZipFile(archive,'w') as z:z.writestr('manifest.json','{"test":true}')
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1400,'height':1000})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    items=[];created=[]
    page.route('**/api/sites/1/updates*',lambda r:r.fulfill(json={'machines':[{'id':19,'name':'NENAD-PC-19','log_collector_version':'1.0.14','log_collector_heartbeat':'2026-11-04T00:00:00Z'}]}))
    def logs(route):
        path=route.request.url
        if path.split('?')[0].endswith('/download'):
            route.fulfill(json={'url':'https://unit.blob.core.windows.net/diagnostics/test.zip','filename':'machine-19-test.zip'});return
        if route.request.method=='POST':
            created.append(route.request.post_data_json)
            items.append(dict(id='00000000-0000-0000-0000-000000000019',status='queued',hours=6,created='2026-11-04T00:00:00Z',size_bytes=None,detail='Waiting for the PC.'))
            route.fulfill(status=202,json={'id':items[0]['id']});return
        route.fulfill(json={'items':items})
    page.route('**/api/sites/1/machines/19/logs**',logs)
    page.route('https://unit.blob.core.windows.net/**',lambda r:r.fulfill(body=archive.getvalue(),headers={'Content-Type':'application/zip','Content-Disposition':'attachment; filename="machine-19-test.zip"'}))
    page.goto('http://127.0.0.1:4298/#logs')
    expect(page.get_by_role('heading',name='Machine logs',exact=True)).to_be_visible()
    page.locator('#logs-hours').select_option('6');page.get_by_role('button',name='Request logs',exact=True).click()
    expect(page.get_by_text('queued',exact=True)).to_be_visible()
    assert created==[{'hours':6}]
    items[0].update(status='ready',size_bytes=len(archive.getvalue()),detail='Logs ready for download.')
    expect(page.get_by_role('button',name='Download ZIP')).to_be_visible(timeout=10000)
    with page.expect_download() as download:page.get_by_role('button',name='Download ZIP').click()
    assert Path(download.value.path()).read_bytes()==archive.getvalue()
    page.screenshot(path='artifacts/machine-logs.png',full_page=True)
    page.set_viewport_size({'width':390,'height':844});page.reload()
    expect(page.get_by_role('heading',name='Machine logs',exact=True)).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
    assert not errors,errors
    browser.close()
print('Machine logs page: request, progress, ready download and mobile layout passed. All log APIs mocked.')
