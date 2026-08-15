# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build definition for kaito."""

import sys
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

sys.setrecursionlimit(5000)

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
                        StringStruct(
                            "FileDescription", "kaito - ZIP/RAR/7z decompression tool"
                        ),
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
_package_metadata = copy_metadata("kaito")

_document_datas = []
for document in (
    "LICENSE",
    "SECURITY.md",
    "THIRD_PARTY_NOTICES.md",
    "bundled/7-ZIP-LICENSE.txt",
    "bundled/SHA256SUMS",
    "bundled/SOURCE-PACKAGE.txt",
):
    path = Path(document)
    if not path.exists():
        raise FileNotFoundError(f"required release document is missing: {path}")
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
        *_package_metadata,
        *_document_datas,
    ],
    hiddenimports=[
        # 自前モジュール（動的 import を除き静的に明示）
        "kaito.i18n",
        "kaito.settings",
        "kaito.unzip",
        "kaito.worker",
        "kaito.gui.theme",
        "kaito.gui.settings_dialog",
        "kaito.gui.unzip_app",
        # 依存
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
    version=_version_info,
)
