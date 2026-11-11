"""Windows WebView2 integration check; synthetic local HTTP/SQLite only."""
import importlib.util
import json
import platform
from pathlib import Path
import sys
import tempfile
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]
spec = importlib.util.spec_from_file_location('gui_fixture', ROOT / 'dev/labs/uid_gui_bench/run.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def main():
    if sys.platform != 'win32':
        raise SystemExit('This check requires actual Windows')
    import webview
    import win32api, win32con
    display = win32api.EnumDisplaySettings(None, win32con.ENUM_CURRENT_SETTINGS)
    display.PelsWidth, display.PelsHeight = 1920, 1080
    status = win32api.ChangeDisplaySettings(display, 0)
    if status != win32con.DISP_CHANGE_SUCCESSFUL:
        raise RuntimeError(f'Cannot configure dedicated CI desktop: {status}')
    from PIL import ImageGrab
    out = ROOT / 'output/uid-windows-gui'
    out.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='uid-windows-ci-'))
    owner, fleet = fixture.setup(root, resolution=True)
    server = fixture.serve(owner, fleet, 0, status_reader=lambda pid: (root/'print-state.txt').read_text())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    window = webview.create_window('Tracker 2.0 Windows CI', f'http://127.0.0.1:{server.server_port}', width=1375, height=1000, x=20, y=20)
    result = {'platform': platform.platform(), 'checks': [], 'success': False,
              'interaction': 'Win32 mouse clicks and drag in native WebView2; DOM assertions'}

    def js(code):
        return window.evaluate_js(code)

    def wait(expr):
        end = time.monotonic()+20
        while time.monotonic()<end:
            try:
                if js(expr): return
            except Exception: pass
            time.sleep(.15)
        raise AssertionError('Timeout: '+expr)

    def check(expr, name):
        assert js(expr), name
        result['checks'].append(name)

    def point(selector):
        from System import Func
        from System.Drawing import Point
        rect = js(f'(()=>{{const e=document.querySelector({json.dumps(selector)});e.scrollIntoView({{block:"center"}});const r=e.getBoundingClientRect();return {{x:r.x+r.width/2,y:r.y+r.height/2,scale:devicePixelRatio}}}})()')
        origin = window.native.Invoke(Func[Point](lambda: window.native.webview.PointToScreen(Point(0, 0))))
        return int(origin.X+rect['x']*rect['scale']), int(origin.Y+rect['y']*rect['scale'])

    def click(selector):
        import ctypes
        x,y=point(selector)
        ctypes.windll.user32.SetCursorPos(x,y)
        ctypes.windll.user32.mouse_event(2,0,0,0,0)
        ctypes.windll.user32.mouse_event(4,0,0,0,0)
        time.sleep(.2)

    def drag(source, target):
        import ctypes
        x,y=point(source); tx,ty=point(target)
        ctypes.windll.user32.SetCursorPos(x,y)
        ctypes.windll.user32.mouse_event(2,0,0,0,0)
        try:
            for i in range(1,21):
                ctypes.windll.user32.SetCursorPos(x+(tx-x)*i//20,y+(ty-y)*i//20)
                time.sleep(.03)
        finally:
            ctypes.windll.user32.mouse_event(4,0,0,0,0)

    def shot(name):
        ImageGrab.grab().save(out / (name+'.png'))

    def refresh():
        js('renderedState="";load()')
        time.sleep(.7)

    def open_resolve():
        click('[data-printer=a] > button')

    def resolve():
        click('#stoppedAck'); click('#lossAck'); click('#resolveSubmit')
        wait('!$("resolveDialog").open')
        refresh()

    def exercise():
        try:
            wait('typeof state!=="undefined" && state?.jobs?.length===1')
            result['user_agent'] = js('navigator.userAgent')
            check('document.body.innerText.includes("Катушки и назначения")', 'UTF-8 Russian copy')
            open_resolve()
            check('$("resolveSubmit").disabled', 'two acknowledgements required')
            click('#stoppedAck')
            check('$("resolveSubmit").disabled', 'one acknowledgement insufficient')
            shot('dialog')
            click('#resolveCancel'); wait('!$("resolveDialog").open'); open_resolve(); wait('$("resolveDialog").open')
            check('!$("stoppedAck").checked&&!$("lossAck").checked', 'cancel resets consent')
            resolve()
            check('state.jobs[0].unlock.mode==="15_minutes"&&!state.jobs[0].unlock.completed', '15-minute window opens')
            js('window.originalPayload={job_key:resolutionSelection.job_key,expected_version:resolutionSelection.resolution_version,confirmed:true,accept_unaccounted:true,mode:"15_minutes"}')
            (root/'clock-offset.txt').write_text('901')
            refresh()
            check('state.jobs[0].unlock.expired', 'deadline expires')
            check('document.querySelector("[data-printer=a] [data-spool] button").disabled', 'expired window blocks GUI transfer')
            js('window.replayDone=false;api("resolve",originalPayload).then(()=>window.replayDone=true)')
            wait('window.replayDone'); refresh()
            check('state.jobs[0].unlock.expired&&state.jobs[0].unlock.revision===1', 'replay does not extend deadline')
            shot('expired')
            fleet.states['a']['state']='offline';refresh()
            check('!state.printers.find(p=>p.id==="a").ready', 'disconnect shown')
            fleet.states['a']['state']='ready';fleet.states['a']['generation']+=1;refresh()
            open_resolve();click('[name=unlockMode][value=until_assignment]');resolve()
            check('state.jobs[0].unlock.mode==="until_assignment"&&state.jobs[0].unlock.deadline===null', 'renewal after reconnect until assignment')
            click('[data-printer=a] [data-spool=manual-black] button')
            check('$("submit").disabled', 'assignment confirmation required')
            click('#ack');click('#submit');wait('!$("dialog").open');refresh()
            check('state.jobs[0].unlock.completed', 'assignment completes unlock')
            drag('[data-printer=a] [data-spool=manual-black] h3', '[data-printer=b] h3')
            wait('$("dialog").open')
            check('selection.mode==="transfer"&&$("printer").value==="b"', 'drag opens correct transfer destination')
            check('$("head").querySelector("option[value=\\"1\\"]").disabled', 'occupied head disabled')
            shot('transfer')
            js('window.transferPayload={spool_id:selection.spool.spool_id,source_printer:selection.assignment.printer_id,source_channel:selection.assignment.channel,target_printer:$("printer").value,target_channel:$("head").value,expected_version:selection.assignment.version,request_id:selection.request_id,confirmed:true}')
            click('#ack');click('#submit');wait('!$("dialog").open');refresh()
            check('state.manual_assignments.find(a=>a.spool_id==="manual-black").printer_id==="b"', 'transfer committed')
            js('window.replayDone=false;api("transfer",transferPayload).then(()=>window.replayDone=true)')
            wait('window.replayDone');refresh()
            check('state.spools.find(s=>s.spool_id==="manual-black").remaining_mg===499702&&state.debits.length===0&&state.resolutions.length===1', 'repeated transfer and resolution preserve balance')
            (root/'clock-offset.txt').write_text('1802');refresh()
            check('state.jobs[0].unlock.completed&&!state.jobs[0].unlock.expired', 'completed window does not relock')
            shot('completed')
            result['success']=True
        except BaseException:
            result['error']=traceback.format_exc()
            try: shot('failure')
            except Exception: pass
        finally:
            result['state']=owner.call('inspect')
            (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            window.destroy()

    try:
        webview.start(exercise, gui='edgechromium', private_mode=True, storage_path=str(root/'webview'))
    finally:
        server.shutdown();server.server_close();owner.close()
    if not result['success']: raise SystemExit(result.get('error','Native window failed'))

if __name__ == '__main__': main()
