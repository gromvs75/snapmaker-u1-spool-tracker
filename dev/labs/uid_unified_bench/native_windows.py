"""External Windows UI Automation of the ordinary EXE and real tray menu."""
import argparse,json,subprocess,tempfile,time,socket,urllib.request,re
from pathlib import Path

def main():
    import win32gui,win32con,win32api
    from pywinauto import Desktop
    from PIL import ImageGrab
    p=argparse.ArgumentParser();p.add_argument('--exe',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True);root=Path(tempfile.mkdtemp(prefix='uid-native-windows-'))
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    proc=subprocess.Popen([str(a.exe.resolve()),'--data',str(root),'--port',str(port),'--window'],cwd=root)
    desktop=Desktop(backend='uia');checks=[];handle=0
    def wait(fn,timeout=60):
        end=time.monotonic()+timeout;last=None
        while time.monotonic()<end:
            try:
                value=fn()
                if value:return value
            except Exception as e:last=str(e)
            if proc.poll() is not None:raise AssertionError('EXE exited: '+str(proc.returncode))
            time.sleep(.3)
        raise AssertionError('UI timeout: '+str(last))
    def tray_menu(label):
        # Use the actual taskbar button and native popup; never call shell.quit directly.
        def icon():
            candidates=desktop.window(class_name='Shell_TrayWnd').descendants(control_type='Button')
            for w in desktop.windows():
                if w.element_info.class_name in ('NotifyIconOverflowWindow','TopLevelWindowForOverflowXamlIsland'):
                    candidates+=w.descendants(control_type='Button')
            return next((b for b in candidates if b.window_text()=='Tracker 2.0 · стенд' and b.is_visible()),None)
        # The overflow UIA subtree can outlive its visible popup after Open.
        # Dismiss it and explicitly reopen hidden icons for every menu action.
        from pywinauto.keyboard import send_keys
        send_keys('{ESC}');time.sleep(.7)
        bar=desktop.window(class_name='Shell_TrayWnd')
        expand=next((b for b in bar.descendants(control_type='Button') if 'hidden icons' in b.window_text().lower()),None)
        if expand:expand.click_input();time.sleep(.7)
        button=wait(icon,15)
        (a.output/('tray-target-'+('open' if label.startswith('Открыть') else 'exit')+'.txt')).write_text(str(button.element_info)+' '+str(button.rectangle()),encoding='utf-8')
        button.click_input(button='right')
        def item():
            for w in desktop.windows():
                for e in w.descendants(control_type='MenuItem'):
                    if e.window_text()==label:return e
            return None
        target=wait(item,15);ImageGrab.grab().save(a.output/('tray-'+('open' if label.startswith('Открыть') else 'exit')+'.png'));target.click_input()
    try:
        handle=wait(lambda:win32gui.FindWindow(None,'Snapmaker U1 Spool Tracker 2.0 · стенд'))
        wait(lambda:win32gui.IsWindowVisible(handle));checks.append('ordinary native window visible')
        rect=win32gui.GetWindowRect(handle)
        assert rect[0]>=0 and rect[1]>=0 and rect[2]<=win32api.GetSystemMetrics(0) and rect[3]<=win32api.GetSystemMetrics(1),rect
        ImageGrab.grab().save(a.output/'native-open.png')
        win32gui.PostMessage(handle,win32con.WM_CLOSE,0,0)
        wait(lambda:not win32gui.IsWindowVisible(handle));assert proc.poll() is None;checks.append('close hides without exiting')
        tray_menu('Открыть Tracker');wait(lambda:win32gui.IsWindowVisible(handle));checks.append('real tray Open restores window')
        tray_menu('Выход');assert proc.wait(30)==0;checks.append('real tray Exit terminates process')
        # Restart with the same disposable data proves the writer lock was released.
        again=subprocess.Popen([str(a.exe.resolve()),'--data',str(root),'--port',str(port)],cwd=root)
        try:
            end=time.monotonic()+60
            while time.monotonic()<end:
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}',timeout=2) as r:assert r.status==200
                    break
                except OSError:time.sleep(.3)
            else:raise AssertionError('Restart failed')
            checks.append('full exit releases database and port')
        finally:again.terminate();again.wait(15)
        (a.output/'native-windows.json').write_text(json.dumps(dict(checks=checks,native_tray_verified=True),indent=2))
    except BaseException:
        ImageGrab.grab().save(a.output/'native-failure.png')
        (a.output/'native-ui-tree.txt').write_text('\n'.join(str(w.element_info) for w in desktop.windows()),encoding='utf-8')
        raise
    finally:
        if proc.poll() is None:proc.terminate();proc.wait(15)
if __name__=='__main__':main()
