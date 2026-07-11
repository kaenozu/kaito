"""
src/kaito/__main__.py
python -m kaito で起動するためのエントリポイント
--version, --self-test CLIオプションを提供
関連: gui/unzip_app.py (GUIエントリ), archive/sevenzip_backend.py (7-Zip依存)
"""

import sys
import tempfile
from pathlib import Path


def _self_test() -> int:
    """システムの健全性チェック"""
    print("kaito self-test")
    print("=" * 40)

    # バージョン
    from kaito.gui.unzip_app import __version__

    print(f"Version: {__version__}")

    # 設定ディレクトリ
    from kaito.settings import SettingsManager

    try:
        sm = SettingsManager()
        print(f"Config dir: {sm._get_path().parent}")
    except Exception as e:
        print(f"Config dir: FAILED ({e})")
        return 1

    # 7-Zip
    from kaito.archive.sevenzip_backend import SevenZipBackend

    backend = SevenZipBackend()
    available, msg = backend.check_tool_availability()
    if available:
        print("7-Zip: OK (bundled or system)")
        # バージョン確認
        import subprocess

        try:
            r = subprocess.run(
                [str(backend._find_tool())], capture_output=True, text=True, timeout=5
            )
            first_line = r.stdout.splitlines()[0] if r.stdout else "(no output)"
            print(f"7-Zip version: {first_line}")
        except Exception as e:
            print(f"7-Zip version check: {e}")
    else:
        print(f"7-Zip: NOT FOUND - {msg}")

    # 対応形式
    from kaito.archive.service import ArchiveService

    svc = ArchiveService()
    exts = sorted(svc.SUPPORTED_EXTENSIONS)
    print(f"Supported formats: {', '.join(exts)}")
    for ext in exts:
        print(
            f"  {ext}: list={svc.is_supported(Path(f'test{ext}'))}, create={svc.is_creation_supported(Path(f'test{ext}'))}"
        )

    # テンポラリディレクトリ
    try:
        td = tempfile.mkdtemp(prefix="kaito_selftest_")
        p = Path(td)
        print(f"Temp dir: {p} (created)")
        p.rmdir()
        print("Temp dir: OK (deleted)")
    except Exception as e:
        print(f"Temp dir: FAILED ({e})")
        return 1

    print("=" * 40)
    print("All checks passed.")
    return 0


def main() -> None:
    args = sys.argv[1:]

    if args and args[0] == "--version":
        from kaito.gui.unzip_app import __version__

        print(f"kaito {__version__}")
        return

    if args and args[0] == "--self-test":
        rc = _self_test()
        sys.exit(rc)

    if args and args[0] == "--backend-info":
        from kaito.archive.sevenzip_backend import SevenZipBackend, SEVENZIP_VERSION

        print(f"Backend: 7-Zip {SEVENZIP_VERSION}")
        print(f"Bundled version requirement: {SEVENZIP_VERSION}")
        print("License: See bundled/7-ZIP-LICENSE.txt")
        backend = SevenZipBackend()
        available, msg = backend.check_tool_availability()
        print(f"Available: {available}")
        if available:
            tool = backend._find_tool()
            print(f"Path: {tool}")
            import hashlib

            sha = hashlib.sha256(tool.read_bytes()).hexdigest()
            print(f"SHA-256: {sha}")
        return

    # GUI起動
    from kaito.gui.unzip_app import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
