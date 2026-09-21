# -*- mode: python ; coding: utf-8 -*-
import sys

from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
)

sys.path.insert(0, SPECPATH)
from storage import APP_VERSION

_parts = [int(p) for p in APP_VERSION.split('.')]
_numvers = tuple((_parts + [0, 0, 0, 0])[:4])
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_numvers, prodvers=_numvers),
    kids=[
        StringFileInfo([
            StringTable('080404b0', [
                StringStruct('FileDescription', 'GenerateTestQuestion'),
                StringStruct('FileVersion', APP_VERSION),
                StringStruct('ProductName', 'GenerateTestQuestion'),
                StringStruct('ProductVersion', APP_VERSION),
                StringStruct('OriginalFilename', 'GenerateTestQuestion.exe'),
            ]),
        ]),
        VarFileInfo([VarStruct('Translation', [2052, 1200])]),
    ],
)

datas = [('data/sources.json', 'data'), ('data/risk_catalog.json', 'data')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('scrapling')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    name='GenerateTestQuestion',
    version=version_info,
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
)
