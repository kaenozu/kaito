# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for kaito
Build: pyinstaller build.spec
"""

import sys
from pathlib import Path

sys.setrecursionlimit(5000)

block_cipher = None

a = Analysis(
    ['src/kaito/__main__.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('src/kaito', 'kaito'),
    ],
    hiddenimports=[
        'PIL._tkinter_finder',
        'tkinterdnd2',
        'customtkinter',
        'patoolib',
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
