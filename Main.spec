# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file.

Uses SPECPATH (set by PyInstaller) to stay path-portable: the spec works no
matter where the repo lives on disk, as long as it is run from inside it.
"""

import os


SPEC_ROOT = os.path.abspath(SPECPATH)
ICON_PATH = os.path.join(SPEC_ROOT, "resources", "icon.icns")


a = Analysis(
    ['Main.py'],
    pathex=[SPEC_ROOT],
    binaries=[],
    datas=[('resources', 'resources')],
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
    a.binaries,
    a.datas,
    [],
    name='Main',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[ICON_PATH] if os.path.exists(ICON_PATH) else None,
)

app = BUNDLE(
    exe,
    name='Main.app',
    icon=ICON_PATH if os.path.exists(ICON_PATH) else None,
    bundle_identifier='com.kurisu.convert',
)
