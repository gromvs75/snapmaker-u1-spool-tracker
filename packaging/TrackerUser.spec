"""User candidate, distinct from installed 1.x and the laboratory executable."""
from pathlib import Path
import datetime
import json
import subprocess
import sys
ROOT=Path(SPECPATH).parent
commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip())
metadata=Path(workpath)/'tracker_build.json'
metadata.parent.mkdir(parents=True,exist_ok=True)
metadata.write_text(json.dumps(dict(commit=commit,dirty=dirty,built_at=datetime.datetime.now(datetime.timezone.utc).isoformat())))
analysis=Analysis([str(ROOT/'src/tracker_app.py')],pathex=[str(ROOT/'src')],
    datas=[(str(ROOT/'src/tracker_uid_gui.html'),'.'),(str(metadata),'.')],
    hiddenimports=['websocket','pystray._darwin'] if sys.platform=='darwin' else ['websocket','pystray._win32','webview.platforms.winforms','webview.platforms.edgechromium'],
    excludes=['pytest','tkinter','PyQt5','PyQt6','PySide2','PySide6'],noarchive=False)
pyz=PYZ(analysis.pure)
exe=EXE(pyz,analysis.scripts,[],exclude_binaries=True,name='Snapmaker-Tracker-2.0-Candidate',console=False,strip=False,upx=False)
coll=COLLECT(exe,analysis.binaries,analysis.datas,strip=False,upx=False,name='Snapmaker-Tracker-2.0-Candidate')
if sys.platform=='darwin':
    app=BUNDLE(coll,name='Snapmaker-Tracker-2.0-Candidate.app',bundle_identifier='app.snapmaker.tracker.v2.candidate',icon=str(ROOT/'packaging/AppIcon.icns'),
        version='2.0.0rc1',info_plist={'CFBundleShortVersionString':'2.0.0rc1','CFBundleVersion':'2.0.0','TrackerSourceCommit':commit,'TrackerBuildDirty':dirty})
