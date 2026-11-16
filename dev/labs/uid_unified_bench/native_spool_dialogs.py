"""Read/click only the child candidate's native Accessibility tree on copied test data."""
import argparse
import ctypes as C
import json
import os
from pathlib import Path
import plistlib
import shutil
import signal
import subprocess
import tempfile
import time
from urllib.request import Request, urlopen


def main():
    parser=argparse.ArgumentParser();parser.add_argument('bundle',type=Path);parser.add_argument('--fixture-results',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    fixture=json.loads(args.fixture_results.read_text());source=Path(fixture['profile'])
    assert source.parent.name.startswith('tracker-graphite-package-'), 'Only synthetic packaged fixture profiles are allowed'
    profile=Path(tempfile.mkdtemp(prefix='tracker-native-spool-dialogs-'))/'profile';shutil.copytree(source,profile)
    assert not (profile/'instance.json').exists()
    bundle=args.bundle.resolve();info=plistlib.loads((bundle/'Contents/Info.plist').read_bytes());checks=[]
    ax=C.CDLL('/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')
    cf=C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    def declare(lib,name,result,*params):
        f=getattr(lib,name);f.restype=result;f.argtypes=params;return f
    ptr=C.c_void_p;integer=C.c_long
    trusted=declare(ax,'AXIsProcessTrusted',C.c_bool);assert trusted(),'Accessibility permission unavailable'
    create=declare(ax,'AXUIElementCreateApplication',ptr,C.c_int)
    attr=declare(ax,'AXUIElementCopyAttributeValue',C.c_int,ptr,ptr,C.POINTER(ptr))
    press=declare(ax,'AXUIElementPerformAction',C.c_int,ptr,ptr)
    string=declare(cf,'CFStringCreateWithCString',ptr,ptr,C.c_char_p,C.c_uint)
    convert=declare(cf,'CFStringGetCString',C.c_bool,ptr,C.c_void_p,integer,C.c_uint)
    typeid=declare(cf,'CFGetTypeID',C.c_ulong,ptr);stringid=declare(cf,'CFStringGetTypeID',C.c_ulong)
    count=declare(cf,'CFArrayGetCount',integer,ptr);at=declare(cf,'CFArrayGetValueAtIndex',ptr,ptr,integer)
    release=declare(cf,'CFRelease',None,ptr);refs=[];strings={}
    def key(s):
        if s not in strings:strings[s]=string(None,s.encode(),0x08000100)
        return strings[s]
    def get(obj,k):
        value=ptr();err=attr(obj,key(k),C.byref(value))
        if err or not value.value:return None
        refs.append(value.value);return value.value
    def text(value):
        if not value or typeid(value)!=stringid():return ''
        buf=C.create_string_buffer(4096);convert(value,buf,len(buf),0x08000100);return buf.value.decode('utf-8')
    def buttons(root,depth=0):
        if depth>25:return []
        found=[];role=text(get(root,'AXRole'))
        if role=='AXButton':found.append((root,[text(get(root,k)) for k in ('AXTitle','AXDescription','AXValue')]))
        children=get(root,'AXChildren')
        if children:
            for i in range(count(children)):found.extend(buttons(at(children,i),depth+1))
        return found
    child=None
    with (out/'process.log').open('w') as log:
        try:
            child=subprocess.Popen([str(bundle/'Contents/MacOS'/info['CFBundleExecutable'])],env=dict(os.environ,TRACKER20_DATA_DIR=str(profile)),stdout=log,stderr=subprocess.STDOUT)
            end=time.monotonic()+30
            while not (profile/'instance.json').exists():
                assert child.poll() is None
                if time.monotonic()>end:raise TimeoutError('Startup')
                time.sleep(.1)
            descriptor=json.loads((profile/'instance.json').read_text())
            def api(route,body=None):
                req=Request(f'http://127.0.0.1:{descriptor["port"]}/api/'+route,data=None if body is None else json.dumps(body).encode(),headers={'X-Tracker-Token':descriptor['token'],'Content-Type':'application/json'})
                with urlopen(req,timeout=15) as r:return json.load(r)
            before=api('state');api('window',dict(action='show'));time.sleep(1)
            root=create(child.pid);refs.append(root)
            def click(caption):
                end=time.monotonic()+10
                while time.monotonic()<end:
                    available=buttons(root);matches=[item for item,names in available if caption in names]
                    if matches:
                        error=press(matches[-1],key('AXPress'));assert error==0,(caption,error);time.sleep(.4);return
                    time.sleep(.25)
                (out/'buttons.json').write_text(json.dumps([names for _,names in available],ensure_ascii=False,indent=2))
                raise AssertionError('Native button unavailable: '+caption)
            import AppKit,Quartz
            app=AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(child.pid)
            assert app.activationPolicy()==1
            def capture(name):
                windows=[w for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionAll,0) if w.get('kCGWindowOwnerPID')==child.pid and w.get('kCGWindowLayer')==0]
                window=max(windows,key=lambda w:w['kCGWindowBounds']['Width']*w['kCGWindowBounds']['Height'])
                subprocess.run(['screencapture','-x','-o','-l',str(window['kCGWindowNumber']),str(out/(name+'.png'))],check=True)
                checks.append(name);print('PASS native '+name,flush=True)
            click('Катушки');capture('library')
            click('Действия с катушкой · Generic Basis');capture('actions')
            click('Параметры');capture('parameters')
            click('Цвет');capture('color');click('Закрыть')
            click('Действия с катушкой · Generic Basis');click('Перенести между принтерами');capture('transfer');click('Закрыть')
            after=api('state');assert after['debits']==before['debits'] and after['spools']==before['spools'] and not after['connections']['connected']
            child.send_signal(signal.SIGTERM);child.wait(20);assert child.returncode==0 and not (profile/'instance.json').exists()
            (out/'results.json').write_text(json.dumps(dict(bundle=str(bundle),profile=str(profile),version=info['CFBundleShortVersionString'],commit=info['TrackerSourceCommit'],checks=checks,unchanged=True,no_dock=True,clean_exit=True),indent=2))
        finally:
            if child and child.poll() is None:child.terminate();child.wait(20)
            for value in reversed(refs):release(value)
            for value in strings.values():release(value)

if __name__=='__main__':main()
