# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['spool_tracker.py'],
    pathex=[],
    binaries=[],
    datas=[],
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
    icon=['AppIcon.icns'],
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
    name='SnapmakerSpoolTracker-1.2.0-beta.1.app',
    icon='AppIcon.icns',
    bundle_identifier='local.snapmaker-spool-tracker.v12beta1',
    info_plist={
        'CFBundleName': 'Snapmaker Spool Tracker Beta',
        'CFBundleDisplayName': 'Snapmaker Spool Tracker 1.2 Beta',
        'CFBundleShortVersionString': '1.2.0',
        'CFBundleVersion': '1',
    },
)
