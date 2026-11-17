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
    datas=[(str(ROOT/'src'/name),'.') for name in ('tracker_uid_gui.html','tracker_user_ui.css','tracker_user_ui.js')]+[(str(metadata),'.'),(str(ROOT/'src/tracker_desktop_133/base.html'),'tracker_desktop_133')]+[(str(p),'tracker_desktop_133') for p in (ROOT/'src/tracker_desktop_133').glob('*') if p.suffix in ('.js','.css')],
    hiddenimports=['websocket','pystray._darwin'] if sys.platform=='darwin' else ['websocket','pystray._win32','webview.platforms.winforms','webview.platforms.edgechromium'],
    # The restored 1.3.3 Windows export confirmation uses tkinter. Omitting it
    # silently cancels exports that need confirmation in the packaged EXE.
    excludes=['pytest','PyQt5','PyQt6','PySide2','PySide6']+(['tkinter'] if sys.platform!='win32' else []),noarchive=False)
pyz=PYZ(analysis.pure)
version_options={}
if sys.platform=='win32':
    from PyInstaller.utils.win32.versioninfo import VSVersionInfo,FixedFileInfo,StringFileInfo,StringTable,StringStruct,VarFileInfo,VarStruct
    version_options['version']=VSVersionInfo(ffi=FixedFileInfo(filevers=(2,0,0,14),prodvers=(2,0,0,14),mask=0x3f,flags=2,OS=0x40004,fileType=1,subtype=0,date=(0,0)),
        kids=[StringFileInfo([StringTable('040904B0',[StringStruct('FileVersion','2.0.0rc14'),StringStruct('ProductVersion','2.0.0rc14'),StringStruct('ProductName','Snapmaker Tracker 2.0 Candidate'),StringStruct('BuildCommit',commit)])]),VarFileInfo([VarStruct('Translation',[1033,1200])])])
exe=EXE(pyz,analysis.scripts,[],exclude_binaries=True,name='Snapmaker-Tracker-2.0-Candidate',console=False,strip=False,upx=False,**version_options)
coll=COLLECT(exe,analysis.binaries,analysis.datas,strip=False,upx=False,name='Snapmaker-Tracker-2.0-Candidate')
if sys.platform=='darwin':
    app=BUNDLE(coll,name='Snapmaker-Tracker-2.0-Candidate.app',bundle_identifier='app.snapmaker.tracker.v2.candidate',icon=str(ROOT/'packaging/AppIcon.icns'),
        version='2.0.0rc14',info_plist={'LSUIElement':True,'CFBundleShortVersionString':'2.0.0rc14','CFBundleVersion':'2.0.0.14','TrackerSourceCommit':commit,'TrackerBuildDirty':dirty})
