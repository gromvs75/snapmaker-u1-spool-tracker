"""Exercise the actual Windows webview with an offline, disposable inventory."""
import faulthandler
import json
import os
import tempfile
import threading
import time

import webview
from dev.labs.spoolman_compare.demo import Demo

faulthandler.enable()
faulthandler.dump_traceback_later(35, repeat=True)
results = []

SCRIPT = r'''
(() => {
 window.__compareProbe = null;
 (async () => {
  const check=(ok,message)=>{if(!ok)throw Error(message);};
  await window.openSpoolmanComparison();
  const dialog=document.getElementById('sc-dialog');
  check(dialog.open,'Comparison dialog did not open');
  check(document.querySelectorAll('.sc-column').length===2,'Missing comparison columns');
  check(document.querySelectorAll('#sc-queue button').length===3,'Missing linked spools');
  const before=await fetch('/api/data').then(r=>r.json());
  const sync=document.getElementById('sc-sync');
  check(!sync.disabled,'Sync unexpectedly disabled');
  await sync.onclick();
  const after=await fetch('/api/data').then(r=>r.json());
  const id=Object.keys(before.spools).find(k=>before.spools[k].spoolman?.id===2);
  before.spools[id].name='[Spoolman #2] ELEGOO RAPID PETG Green';
  check(JSON.stringify(before)===JSON.stringify(after),'Sync changed more than the name');
  check(sync.disabled,'Synced name still actionable');
  document.querySelector('[data-sc-filter="same"]').click();
  check(document.querySelectorAll('#sc-source-list button').length===1,'Matching filter failed');
  document.querySelector('[data-sc-filter="different"]').click();
  check(document.querySelectorAll('#sc-source-list button').length===2,'Difference filter failed');
  document.querySelector('[data-sc-filter="local"]').click();
  document.querySelector('#sc-source-list button').click();
  check(sync.disabled,'Local spool can be synced');
  dialog.close();
  await window.openSpoolmanComparison();
  check(dialog.open,'Comparison did not reopen');
  window.__compareProbe={result:'PASS', checks:['dialog','two columns','name-only sync','filters','local protection','reopen']};
 })().catch(e=>{window.__compareProbe={result:'FAIL',error:String(e),stack:e.stack};});
 return true;
})()
'''


def probe(window):
    try:
        assert window.events.loaded.wait(20), 'Webview did not load'
        window.evaluate_js(SCRIPT)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            result = window.evaluate_js('window.__compareProbe || null')
            if result:
                results.append(result)
                print(json.dumps(result), flush=True)
                break
            time.sleep(.1)
        else:
            raise AssertionError('Comparison probe timed out')
    except Exception as exc:
        results.append({'result': 'FAIL', 'error': repr(exc)})
        print(json.dumps(results[-1]), flush=True)
    finally:
        window.destroy()


def watchdog():
    time.sleep(60)
    print('FAIL: Windows comparison window did not exit', flush=True)
    os._exit(2)


with tempfile.TemporaryDirectory(prefix='tracker-compare-probe-') as directory:
    with Demo(directory) as demo:
        threading.Thread(target=watchdog, daemon=True).start()
        window = webview.create_window('Tracker offline comparison probe', demo.url,
                                       width=1400, height=1050)
        try:
            webview.start(probe, window)
        finally:
            faulthandler.cancel_dump_traceback_later()
        assert len(results) == 1 and results[0]['result'] == 'PASS', results
