"""External smoke check of the EXE's ordinary no-argument launch."""
import argparse
import ctypes
import json
from pathlib import Path
import subprocess
import tempfile
import time
from PIL import ImageGrab


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--exe',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root=Path(tempfile.gettempdir())
    before=set(root.glob('uid-gui-bench-*'))
    process=subprocess.Popen([str(args.exe.resolve())],cwd=args.exe.parent)
    handle=0
    try:
        end=time.monotonic()+45
        while time.monotonic()<end and process.poll() is None:
            handle=ctypes.windll.user32.FindWindowW(None,'Tracker 2.0 · стенд')
            if handle:break
            time.sleep(.2)
        if not handle:raise AssertionError('Normal EXE did not open its native window')
        time.sleep(3)
        ImageGrab.grab().save(args.output/'normal-launch.png')
        ctypes.windll.user32.PostMessageW(handle,0x0010,0,0)
        assert process.wait(timeout=30)==0
        created=set(root.glob('uid-gui-bench-*'))-before
        assert len(created)==1
        data=created.pop()
        info=json.loads((data/'run-info.json').read_text(encoding='utf-8'))
        state=json.loads((data/'verification.json').read_text(encoding='utf-8'))
        assert info['native_gui_requested'] and info['native_event_loop_returned']
        assert len(state['spools'])==2 and not state['debits']
        (args.output/'normal-launch.json').write_text(json.dumps({'passed':True,'info':info,'state':state},ensure_ascii=False,indent=2),encoding='utf-8')
    finally:
        if process.poll() is None:
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],check=False)

if __name__=='__main__':main()
