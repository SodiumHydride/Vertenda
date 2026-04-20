# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file.

Uses SPECPATH (set by PyInstaller) to stay path-portable: the spec works no
matter where the repo lives on disk, as long as it is run from inside it.

Cross-platform ffmpeg handling: the repo may accumulate both a macOS
``ffmpeg`` binary and a Windows ``ffmpeg.exe`` (e.g. after using the
``--download-ffmpeg`` option of both build scripts). The data-collection
function below strips out the wrong-platform binary so the resulting bundle
is neither bloated nor confused at runtime.
"""

import os
import sys


SPEC_ROOT = os.path.abspath(SPECPATH)
if sys.platform == "win32":
    ICON_PATH = os.path.join(SPEC_ROOT, "resources", "favicon.ico")
elif sys.platform == "darwin":
    ICON_PATH = os.path.join(SPEC_ROOT, "resources", "icon.icns")
else:
    ICON_PATH = None

_OTHER_PLATFORM_BINARIES = (
    {"ffmpeg", "ffprobe"} if sys.platform == "win32"
    else {"ffmpeg.exe", "ffprobe.exe"}
)


def collect_resources():
    """Walk resources/ and build PyInstaller (src, dst_dir) pairs."""
    src_root = os.path.join(SPEC_ROOT, "resources")
    pairs = []
    for dirpath, _dirs, files in os.walk(src_root):
        for fname in files:
            if fname in _OTHER_PLATFORM_BINARIES:
                continue
            if fname == ".DS_Store":
                continue
            src = os.path.join(dirpath, fname)
            rel_dir = os.path.relpath(dirpath, src_root)
            dst_dir = "resources" if rel_dir == "." else os.path.join("resources", rel_dir)
            pairs.append((src, dst_dir))
    return pairs


a = Analysis(
    ['Main.py'],
    pathex=[SPEC_ROOT],
    binaries=[],
    datas=collect_resources(),
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
    name='Vertenda',
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
    icon=[ICON_PATH] if ICON_PATH and os.path.exists(ICON_PATH) else None,
)

app = BUNDLE(
    exe,
    name='Vertenda.app',
    icon=ICON_PATH if ICON_PATH and os.path.exists(ICON_PATH) else None,
    bundle_identifier='com.kurisu.vertenda',
)
