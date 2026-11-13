# Isolated settings/recovery application. Never replaces the stable app bundle.
from pathlib import Path
import sys
ROOT=Path(SPECPATH).parent
analysis=Analysis([str(ROOT/'dev/labs/uid_settings_bench/app.py')],
    pathex=[str(ROOT/'src'),str(ROOT)],datas=[(str(ROOT/'src/tracker_uid_gui.html'),'.')],
    hiddenimports=['websocket','pystray._darwin'] if sys.platform=='darwin' else ['websocket','pystray._win32','webview.platforms.winforms','webview.platforms.edgechromium'],
    excludes=['pytest','tkinter','PyQt5','PyQt6','PySide2','PySide6'],noarchive=False)
pyz=PYZ(analysis.pure)
exe=EXE(pyz,analysis.scripts,[],exclude_binaries=True,name='Tracker-2.0-Settings-Bench',console=False,strip=False,upx=False)
coll=COLLECT(exe,analysis.binaries,analysis.datas,strip=False,upx=False,name='Tracker-2.0-Settings-Bench')
if sys.platform=='darwin':
    app=BUNDLE(coll,name='Tracker-2.0-Settings-Bench.app',bundle_identifier='local.tracker.uid.settings.bench',icon=str(ROOT/'packaging/AppIcon.icns'))
