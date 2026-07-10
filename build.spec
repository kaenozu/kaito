# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for kaito
Build: pyinstaller build.spec
"""

import sys
from pathlib import Path

sys.setrecursionlimit(5000)

block_cipher = None

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
)
