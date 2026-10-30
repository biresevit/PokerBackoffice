"""Ensure a slow/failing activity chart never hides the Overview cards."""
import asyncio
from playwright.async_api import async_playwright

async def main():
 async with async_playwright() as p:
  browser=await p.chromium.launch(headless=True)
  page=await browser.new_page(viewport={'width':1440,'height':1000})
  errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  chart_finished=False;attempts=0
  async def metrics(route):
   nonlocal chart_finished,attempts
   attempts+=1
   if attempts==1:
    await asyncio.sleep(6)
    chart_finished=True
    await route.fulfill(status=503,content_type='application/json',body='{"error":"Simulated chart outage"}')
   else:await route.continue_()
  await page.route('**/api/sites/1/metrics?*',metrics)
  await page.goto('http://127.0.0.1:4295',wait_until='domcontentloaded')
  cards=page.locator('#workspace .stats .stat-value')
  await cards.first.wait_for(timeout=5000)
  assert not chart_finished,'Cards waited for the graph request'
  await page.get_by_role('button',name='Retry chart',exact=True).wait_for(timeout=10000)
  assert await cards.count()==4
  await page.screenshot(path='artifacts/overview-chart-failure.png')
  await page.get_by_role('button',name='Retry chart',exact=True).click()
  await page.locator('#entry-chart-filter').wait_for(timeout=15000)
  assert await cards.count()==4
  assert not errors,errors
  await browser.close()
  print('Overview cards render before a slow graph; graph failure and retry preserve all cards.')

asyncio.run(main())
