"""Cross-platform browser smoke test against real handlers and disposable inventory."""
import json
import os
from pathlib import Path
import subprocess
import sys
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]

def main():
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT/'src'), str(ROOT)]))
    process = subprocess.Popen([sys.executable, '-u', '-m', 'dev.labs.settings_tracker.server'], cwd=ROOT, env=env, stdout=subprocess.PIPE, text=True)
    try:
        info = json.loads(process.stdout.readline())
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width':1440,'height':1000})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('dialog', lambda d: d.accept())
            page.goto(info['url'])
            page.locator('#nav-spools').click()
            assert page.locator('.inventory-tabs button').count() == 2
            assert page.locator('#spools-table svg').count() == 4
            page.locator('#inventory-search').fill('green')
            assert page.locator('#spools-table tr:visible').count() == 1
            page.locator('#inventory-search').fill('')
            page.locator('[data-inventory-tab="slots"]').click()
            page.locator('#inventory-create-assign').click()
            page.locator('#inventory-add-dialog').wait_for(state='visible')
            page.locator('#new-name').fill('CI spool')
            page.locator('#new-mat').fill('PLA')
            page.locator('#create-head').select_option('4')
            with page.expect_response(lambda r:r.url.endswith('/api/spools/add')) as response:
                page.locator('#t-add-btn').click()
            assert response.value.status == 200
            page.locator('#inventory-add-dialog').wait_for(state='hidden')
            data = page.request.get(info['url']+'/api/data').json()
            assert data['spools'][data['slots']['4']]['name'] == 'CI spool'
            page.reload()
            page.locator('#nav-spools').click()
            row=page.locator('#spools-table tr').filter(has_text='CI spool')
            row.locator('.inventory-param-button').click()
            assert page.locator('#cal-spool option:checked').inner_text() == 'CI spool'
            page.locator('#inventory-param-dialog .dialog-close').click()
            page.locator('#nav-settings').click()
            page.locator('[data-settings-section="accounting"]').click()
            page.locator('#reserve-input').fill('12')
            with page.expect_response(lambda r:r.url.endswith('/api/settings')):
                page.locator('#reserve-save').click()
            assert page.request.get(info['url']+'/api/data').json()['safety_margin_g'] == 12
            page.locator('[data-settings-section="spoolman"]').click()
            page.locator('[data-spool-id="2"]').click()
            boxes=page.locator('.sm-inspector button').evaluate_all('(es)=>es.map(e=>({x:e.getBoundingClientRect().x,w:e.getBoundingClientRect().width}))')
            assert len({(b['x'],b['w']) for b in boxes}) == 1
            page.locator('#nav-spools').click()
            page.set_viewport_size({'width':700,'height':900})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not errors, errors
            browser.close()
        print('PASS: sidebar, search, create-and-assign, persistence, parameters, settings, button alignment, responsive layout; no page errors')
    finally:
        process.terminate()
        process.wait(timeout=15)

if __name__ == '__main__': main()
