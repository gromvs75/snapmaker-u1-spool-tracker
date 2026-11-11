# Isolated 2.0 bench executable, not the stable installed Tracker.
from pathlib import Path
ROOT = Path(SPECPATH).parent
analysis = Analysis(
    [str(ROOT/'dev/labs/uid_windows_bench/app.py')],
    pathex=[str(ROOT/'src'),str(ROOT)],
    datas=[(str(ROOT/'src/tracker_uid_gui.html'),'.')],
    hiddenimports=['webview.platforms.winforms','webview.platforms.edgechromium'],
    excludes=['pytest','tkinter','PyQt5','PyQt6','PySide2','PySide6'],
    noarchive=False, optimize=0,
)
pyz = PYZ(analysis.pure)
exe = EXE(pyz,analysis.scripts,analysis.binaries,analysis.datas,[],
          name='Tracker-2.0-Windows-Bench',console=False,debug=False,
          strip=False,upx=False,disable_windowed_traceback=False)
