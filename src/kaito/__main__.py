"""python -m kaito / kaito.exe のエントリポイント。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


def _version() -> str:
    from kaito.gui.unzip_app import __version__

    return __version__


def _self_test() -> int:
    """配布物と実行環境の最低限の健全性を確認する。"""
    print("kaito self-test")
    print("=" * 40)
    print(f"Version: {_version()}")

    from kaito.settings import SettingsManager

    try:
        manager = SettingsManager()
        print(f"Config dir: {manager._get_path().parent}")
    except Exception as exc:
        print(f"Config dir: FAILED ({exc})")
        return 1

    from kaito.archive.sevenzip_backend import SevenZipBackend

    try:
        info = SevenZipBackend().backend_info()
    except Exception as exc:
        print(f"7-Zip: FAILED ({exc})")
        return 1

    print(f"7-Zip: OK ({info['source']})")
    print(f"7-Zip version: {info['version']}")
    print(f"7-Zip integrity: {info['integrity']}")
    if info["integrity"] != "ok":
        return 1
    if bool(getattr(sys, "frozen", False)) and info["source"] != "bundled":
        print("7-Zip source: FAILED (frozen app must use bundled backend)")
        return 1

    from kaito.archive.service import ArchiveService

    service = ArchiveService()
    extensions = sorted(service.SUPPORTED_EXTENSIONS)
    print(f"Supported formats: {', '.join(extensions)}")
    for extension in extensions:
        print(
            f"  {extension}: list={service.is_supported(Path(f'test{extension}'))}, "
            f"create={service.is_creation_supported(Path(f'test{extension}'))}"
        )

    try:
        with tempfile.TemporaryDirectory(prefix="kaito_selftest_") as temp_dir:
            path = Path(temp_dir)
            probe = path / "probe.txt"
            probe.write_text("ok", encoding="utf-8")
            if probe.read_text(encoding="utf-8") != "ok":
                raise OSError("temporary file round-trip failed")
        print("Temp dir: OK")
    except Exception as exc:
        print(f"Temp dir: FAILED ({exc})")
        return 1

    print("=" * 40)
    print("All checks passed.")
    return 0


def _backend_info(as_json: bool) -> int:
    from kaito.archive.sevenzip_backend import SevenZipBackend

    try:
        info = SevenZipBackend().backend_info()
    except Exception as exc:
        if as_json:
            print(
                json.dumps({"available": False, "error": str(exc)}, ensure_ascii=False)
            )
        else:
            print(f"Available: False\nError: {exc}")
        return 1

    if as_json:
        print(json.dumps(info, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Available: {info['available']}")
        print(f"Source: {info['source']}")
        print(f"Path: {info['path']}")
        print(f"Version: {info['version']}")
        print(f"SHA-256: {info['sha256']}")
        print(f"Expected SHA-256: {info['expected_sha256']}")
        print(f"Integrity: {info['integrity']}")
    return 0


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "--version":
        print(f"kaito {_version()}")
        return
    if args and args[0] == "--self-test":
        raise SystemExit(_self_test())
    if args and args[0] == "--backend-info":
        raise SystemExit(_backend_info("--json" in args[1:]))

    from kaito.gui.unzip_app import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
