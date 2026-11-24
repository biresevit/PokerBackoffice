"""Overview's real chart helpers with synthetic human-seat observations."""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = (ROOT/'frontend/app.js').read_text(encoding='utf-8')
    helpers = source[source.index('const entryTrendChart ='):source.index('const machineMetricChart =')]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width':1200,'height':800})
        page.set_content('<style>svg{width:900px;height:280px}</style><main></main>')
        page.add_script_tag(content='''const $=(s,r=document)=>r.querySelector(s),esc=v=>String(v??''),empty=()=>'';
        '''+helpers+'''
        attachEntryTrendChart(document.querySelector('main'),{format:'RING',timezone:'Europe/Rome',
          human_seats:{note:'Unknown means no sample.',step_minutes:1},points:[
          {at:'2026-11-24T10:00:00Z',scheduled:4,running:3,humans:9,human_partial:true},
          {at:'2026-11-24T10:01:00Z',scheduled:4,running:3,humans:null},
          {at:'2026-11-24T10:02:00Z',scheduled:4,running:4,humans:0}]});''')
        assert 'Human seats (sampled average)' in page.locator('.entry-chart-legend').inner_text()
        path = page.locator('.human-seats').get_attribute('d')
        assert path.count('M') == 2, path  # Missing data breaks the line.
        assert 'Human seats (sampled average): 0' in page.locator('.entry-readout').inner_text()
        page.locator('svg').focus()
        page.keyboard.press('ArrowLeft')
        assert 'Human seats (sampled average): unknown' in page.locator('.entry-readout').inner_text()
        page.keyboard.press('ArrowLeft')
        assert 'Human seats (sampled average): ≥9' in page.locator('.entry-readout').inner_text()
        browser.close()
    print('PASS: Overview human line, scale, legend, zero and unknown hover values, and gaps.')


if __name__ == '__main__': main()
