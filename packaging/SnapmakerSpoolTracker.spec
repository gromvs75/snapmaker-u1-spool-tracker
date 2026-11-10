# -*- mode: python ; coding: utf-8 -*-


from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / 'src' / 'spool_tracker.py')],
    pathex=[str(ROOT / 'src'), str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / 'LICENSE'), 'licenses'), (str(ROOT / 'docs' / 'licenses'), 'licenses'), (str(ROOT / 'docs' / 'guides'), 'guides')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SnapmakerSpoolTracker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(ROOT / 'packaging' / 'AppIcon.icns')],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SnapmakerSpoolTracker',
)
app = BUNDLE(
    coll,
    name='SnapmakerSpoolTracker-1.3.2.app',
    icon=str(ROOT / 'packaging' / 'AppIcon.icns'),
    bundle_identifier='local.snapmaker-spool-tracker.v12beta1',
    info_plist={
        'LSUIElement': True,
        'CFBundleName': 'Snapmaker Spool Tracker',
        'CFBundleDisplayName': 'Snapmaker Spool Tracker 1.3.2',
        'CFBundleShortVersionString': '1.3.2',
        'CFBundleVersion': '16',
    },
)
