# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build definition for kaito 0.9.1.dev0."""

import sys
from pathlib import Path

sys.setrecursionlimit(5000)

_python_root = Path(sys.base_prefix)
_tk_binaries = [
    (str(_python_root / "DLLs" / name), ".")
    for name in ("_tkinter.pyd", "tk86t.dll", "tcl86t.dll")
    if (_python_root / "DLLs" / name).exists()
]
_tk_datas = [
    (str(_python_root / "tcl" / name), f"tcl/{name}")
    for name in ("tcl8.6", "tk8.6")
    if (_python_root / "tcl" / name).exists()
]
_tkinter_package = _python_root / "Lib" / "tkinter"

_document_datas = []
for document in (
    "LICENSE",
    "SECURITY.md",
    "THIRD_PARTY_NOTICES.md",
    "bundled/7-ZIP-LICENSE.txt",
    "bundled/SHA256SUMS",
):
    path = Path(document)
    if path.exists():
        destination = "bundled" if path.parent.name == "bundled" else "."
        _document_datas.append((str(path), destination))

_bundled_binaries = []
for path in (Path("bundled") / "7z.exe", Path("bundled") / "7z.dll"):
    if not path.is_file():
        raise FileNotFoundError(f"required bundled backend is missing: {path}")
    _bundled_binaries.append((str(path), "bundled"))

analysis = Analysis(
    ["src/kaito/__main__.py"],
    pathex=[],
    binaries=_tk_binaries + _bundled_binaries,
    datas=[
        ("src/kaito", "kaito"),
        *_tk_datas,
        (str(_tkinter_package), "tkinter"),
        *_document_datas,
    ],
    hiddenimports=[
        "PIL._tkinter_finder",
        "tkinterdnd2",
        "customtkinter",
        "tkinter",
        "tkinter.filedialog",
        "tkinter.ttk",
        "_tkinter",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["patoolib", "patool"],
    noarchive=False,
    optimize=0,
)

python_archive = PYZ(analysis.pure)

executable = EXE(
    python_archive,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="kaito",
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
