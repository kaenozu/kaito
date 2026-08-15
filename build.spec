# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for kaito
Build: pyinstaller build.spec
"""

import sys
import tomllib
from pathlib import Path

sys.setrecursionlimit(5000)

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

block_cipher = None

# --- バージョン情報（pyproject.toml を単一の真実源とする） ---

def _version_tuple(version: str) -> tuple[int, int, int, int]:
    parts = [int(part) for part in version.split(".")]
    parts.extend([0] * (4 - len(parts)))
    return tuple(parts[:4])  # type: ignore[return-value]


with open("pyproject.toml", "rb") as _version_file:
    _project_version = tomllib.load(_version_file)["project"]["version"]

_version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=_version_tuple(_project_version),
        prodvers=_version_tuple(_project_version),
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName", "kaito"),
                        StringStruct("FileDescription", "kaito - ZIP/RAR/7z decompression tool"),
                        StringStruct("FileVersion", _project_version),
                        StringStruct("InternalName", "kaito"),
                        StringStruct("OriginalFilename", "kaito.exe"),
                        StringStruct("ProductName", "kaito"),
                        StringStruct("ProductVersion", _project_version),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

# Some embedded/managed Python distributions contain Tkinter but PyInstaller's
# Tcl/Tk probe cannot locate it. Bundle the runtime pieces explicitly.
_python_root = Path(sys.base_prefix)
_tk_binaries = [
    (str(_python_root / 'DLLs' / name), '.')
    for name in ('_tkinter.pyd', 'tk86t.dll', 'tcl86t.dll')
    if (_python_root / 'DLLs' / name).exists()
]
_tk_datas = [
    (str(_python_root / 'tcl' / name), f'tcl/{name}')
    for name in ('tcl8.6', 'tk8.6')
    if (_python_root / 'tcl' / name).exists()
]
_tkinter_package = (_python_root / 'Lib' / 'tkinter')

a = Analysis(
    ['src/kaito/__main__.py'],
    pathex=[],
    binaries=_tk_binaries,
    datas=[
        ('src/kaito', 'kaito'),
        *_tk_datas,
        (str(_tkinter_package), 'tkinter'),
    ],
    hiddenimports=[
        # 自前モジュール（動的 import を除き静的に明示）
        'kaito.i18n',
        'kaito.settings',
        'kaito.unzip',
        'kaito.worker',
        'kaito.gui.theme',
        'kaito.gui.settings_dialog',
        'kaito.gui.unzip_app',
        # 依存
        'PIL._tkinter_finder',
        'tkinterdnd2',
        'customtkinter',
        'patoolib',
        'tkinter',
        'tkinter.filedialog',
        'tkinter.ttk',
        '_tkinter',
    ],
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
    name='kaito',
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
    icon=None,
    version=_version_info,
)
