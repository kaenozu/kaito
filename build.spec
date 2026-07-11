# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for kaito (v0.9.1.dev0)
Build: pyinstaller build.spec
CI also uses: pyinstaller build.spec
"""

import sys
from pathlib import Path

sys.setrecursionlimit(5000)

block_cipher = None

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

# ライセンスファイルを含める
_license_datas = []
for lic in ('LICENSE', 'bundled/7-ZIP-LICENSE.txt', 'LICENSE.txt', 'LICENSE.rst',):
    p = Path(lic)
    if p.exists():
        _license_datas.append((str(p), '.'))

# 同梱7-Zip (7z.exeと7z.dllをbinaryとして扱う)
_bundled_binaries = []
_bundled_datas = []
for p in Path('bundled').iterdir():
    if not p.is_file():
        continue
    if p.suffix.lower() in ('.exe', '.dll'):
        _bundled_binaries.append((str(p), 'bundled'))
    else:
        _bundled_datas.append((str(p), 'bundled'))

a = Analysis(
    ['src/kaito/__main__.py'],
    pathex=[],
    binaries=_tk_binaries + _bundled_binaries,
    datas=[
        ('src/kaito', 'kaito'),
        *_tk_datas,
        (str(_tkinter_package), 'tkinter'),
        *_license_datas,
        *_bundled_datas,
    ],
    hiddenimports=[
        'PIL._tkinter_finder',
        'tkinterdnd2',
        'customtkinter',
        'tkinter',
        'tkinter.filedialog',
        'tkinter.ttk',
        '_tkinter',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'patoolib',
        'patool',
    ],
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