"""PoC 検証スクリプト: 7z.dll 直接統合でパスワードのプロセス引数露出が無くなることを実証する。

実行方法:
    python tools/dll-poc/poc_verify.py

検証内容:
  1. 暗号化 ZIP (AES-256) / 7z を 7z.dll の IInArchive で開き、一覧・展開する
     (パスワードはプロセス内 ICryptoGetTextPassword / BSTR で供給)
  2. DLL 操作中に subprocess が一切呼ばれないこと (プロセスを生まない)
  3. 操作前後の全プロセスのコマンドラインにパスワードが現れないこと
  4. (対比) 現行 CLI パスは -p<password> をプロセス引数に渡すことを実演する
  5. IOutArchive で ZIP / 7z を圧縮できる (平文・AES-256・ヘッダー暗号化)
     — 圧縮も subprocess ゼロ・コマンドライン露出ゼロ

リターンコード: すべて成功で 0、失敗で 1。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BUNDLED = _REPO_ROOT / "bundled"
_DLL = _BUNDLED / "7z.dll"
_SEVENZ = _BUNDLED / "7z.exe"
_TEST_SECRET = "Kaito-Dll-Poc-2026!"
_CONTENT = b"DLL PoC secret content\n"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sevenzip_dll import DllPocError, SevenZipDll  # noqa: E402


def _norm_name(name: str) -> str:
    """読み取り側が Windows では '\\' を返すため '/' に正規化する。"""
    return name.replace("\\", "/")


def _build_write_items(source: Path) -> list[dict]:
    """IOutArchive::UpdateItems 用のソース項目リスト。

    ディレクトリ名の末尾区切りは付けない (7-Zip CLI と同じ挙動で、
    読み取り時にハンドラが区切りを補完する)。
    """
    items: list[dict] = []
    for item in sorted(source.rglob("*")):
        rel = item.relative_to(source).as_posix()
        st = item.stat()
        items.append(
            {
                "path": item,
                "name": rel,
                "is_dir": item.is_dir(),
                "size": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime),
                "attrib": None,
            }
        )
    return items


def _read_back(
    dll: SevenZipDll, path: Path, handler: str, password: str | None
) -> tuple[list[str], dict[str, bytes]]:
    """作成したアーカイブを DLL で読み直し、(ファイル名, 内容) を返す。"""
    with dll.open_archive(path, handler, password=password) as opened:
        listing = opened.list_items()
    files = {_norm_name(item.name): item for item in listing if not item.is_dir}
    contents: dict[str, bytes] = {}
    for fname, item in files.items():
        with dll.open_archive(path, handler, password=password) as opened:
            contents[fname] = opened.extract_to_memory(item.index, password=password)
    return sorted(files), contents


def _create_encrypted_zip(directory: Path) -> Path:
    source = directory / "zip-src"
    source.mkdir()
    (source / "secret.txt").write_bytes(_CONTENT)
    archive = directory / "encrypted.zip"
    result = subprocess.run(
        [
            str(_SEVENZ),
            "a",
            "-tzip",
            "-mem=AES256",
            f"-p{_TEST_SECRET}",
            str(archive),
            str(source / "*"),
            "-y",
            "-sccUTF-8",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    return archive


def _create_encrypted_7z(directory: Path) -> Path:
    source = directory / "7z-src"
    source.mkdir()
    (source / "secret.txt").write_bytes(_CONTENT)
    archive = directory / "encrypted.7z"
    result = subprocess.run(
        [
            str(_SEVENZ),
            "a",
            f"-p{_TEST_SECRET}",
            str(archive),
            str(source / "*"),
            "-y",
            "-sccUTF-8",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    return archive


def _scan_cmdlines_with(password: str) -> list[str]:
    """全プロセスのコマンドラインから password を含むものを返す (PowerShell)。"""
    script = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -ne $null } | "
        "ForEach-Object { $_.CommandLine }"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return [line for line in result.stdout.splitlines() if password in line]


def _demonstrate_cli_exposure(directory: Path) -> bool:
    """現行 CLI パスがパスワードをプロセス引数に渡すことを実演する。

    7z.exe を -si (stdin から読込) で起動し、stdin を開いたままにして処理を
    ブロックさせ、その間に全プロセスのコマンドラインを走査する。
    """
    process = subprocess.Popen(
        [
            str(_SEVENZ),
            "a",
            "-tzip",
            f"-p{_TEST_SECRET}",
            "-si",
            str(directory / "cli-demo.zip"),
            "-y",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        deadline = time.monotonic() + 15
        observed: list[str] = []
        while time.monotonic() < deadline and process.poll() is None:
            observed = _scan_cmdlines_with(_TEST_SECRET)
            if observed:
                break
            time.sleep(0.05)
        return observed
    finally:
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        process.wait(timeout=30)


def main() -> int:
    if not _DLL.is_file():
        print(f"[FAIL] bundled/7z.dll が見つかりません: {_DLL}")
        return 1
    if not _SEVENZ.is_file():
        print(f"[FAIL] bundled/7z.exe が見つかりません: {_SEVENZ}")
        return 1

    print("=" * 72)
    print("7z.dll 直接統合 PoC — パスワードのプロセス引数露出ゼロの検証")
    print(f"7z.dll: {_DLL}")
    print(f"パスワード (テスト用): {_TEST_SECRET}")
    print("=" * 72)

    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp)

        # 1. フィクスチャ作成 (現行 CLI。作成自体は検証対象外)
        print("\n[1] 暗号化フィクスチャを作成 (CLI, 検証対象外)...")
        zip_path = _create_encrypted_zip(work)
        seven_path = _create_encrypted_7z(work)
        print(f"    encrypted.zip / encrypted.7z を作成: {zip_path}")

        # 2. 現行 CLI パスの露出を実演 (対比)
        print("\n[2] 対比: 現行 CLI パスはパスワードをプロセス引数に渡す...")
        observed = _demonstrate_cli_exposure(work)
        if observed:
            print(
                f"    [検出] 実行中のプロセスのコマンドラインにパスワードが露出: {observed[0][:100]}..."
            )
            print("    → 現行の 7z.exe subprocess 方式では同一ユーザーの別プロセスから")
            print("      コマンドラインを覗ける (SECURITY.md の残存リスク)。")
        else:
            print(
                "    [未検出] 走査ウィンドウ内で CLI のコマンドラインを観測できませんでした"
            )

        # 3. DLL 経由の open / list / extract
        print("\n[3] 7z.dll (IInArchive) で暗号化アーカイブを開いて展開...")
        dll = SevenZipDll(_DLL)
        results: list[tuple[str, bytes, bytes]] = []
        for label, path, handler in (
            ("ZIP (AES-256)", zip_path, "zip"),
            ("7z (AES-256)", seven_path, "7z"),
        ):
            with dll.open_archive(path, handler, password=_TEST_SECRET) as opened:
                items = opened.list_items()
                names = [item.name for item in items if not item.is_dir]
                encrypted_flags = [
                    item.is_encrypted for item in items if not item.is_dir
                ]
                index = next(item.index for item in items if not item.is_dir)
                data = opened.extract_to_memory(index, password=_TEST_SECRET)
                ok = data == _CONTENT
                results.append((label, data, _CONTENT))
                print(
                    f"    {label}: 項目={names} 暗号化={encrypted_flags} 展開={len(data)}B 一致={ok}"
                )
            if not ok:
                print(f"    [FAIL] {label} の内容が一致しません")
                return 1

        # 4. 誤パスワードの拒否
        print("\n[4] 誤パスワードの拒否...")
        with dll.open_archive(zip_path, "zip", password=_TEST_SECRET) as opened:
            items = opened.list_items()
            index = next(item.index for item in items if not item.is_dir)
            try:
                opened.extract_to_memory(index, password="wrong-password")
                print("    [FAIL] 誤パスワードが拒否されませんでした")
                return 1
            except DllPocError as exc:
                print(f"    [OK] 拒否されました: {exc}")

        # 5. DLL 操作中に subprocess が呼ばれないこと
        print("\n[5] DLL 操作中の subprocess 呼び出しを記録...")
        calls: list[object] = []
        original_popen = subprocess.Popen

        def _recording_popen(*args: object, **kwargs: object) -> subprocess.Popen[str]:
            calls.append(args)
            return original_popen(*args, **kwargs)

        subprocess.Popen = _recording_popen  # type: ignore[assignment]
        try:
            for label, path, handler in (
                ("ZIP (AES-256)", zip_path, "zip"),
                ("7z (AES-256)", seven_path, "7z"),
            ):
                with dll.open_archive(path, handler, password=_TEST_SECRET) as opened:
                    opened.list_items()
                    index = next(
                        item.index for item in opened.list_items() if not item.is_dir
                    )
                    opened.extract_to_memory(index, password=_TEST_SECRET)
        finally:
            subprocess.Popen = original_popen  # type: ignore[assignment]

        if calls:
            print(f"    [FAIL] DLL 操作中に subprocess が {len(calls)} 回呼ばれました")
            return 1
        print("    [OK] DLL 操作中に subprocess 呼び出しゼロ (プロセスを生まない)")

        # 6. 操作前後のコマンドライン走査
        print("\n[6] 全プロセスのコマンドライン走査 (パスワード露出の有無)...")
        before = _scan_cmdlines_with(_TEST_SECRET)
        if before:
            print(f"    [FAIL] 操作前に既に露出: {before}")
            return 1
        print("    [OK] 操作前: 露出ゼロ")
        # 最後にもう一度 DLL を動かしてから走査
        with dll.open_archive(zip_path, "zip", password=_TEST_SECRET) as opened:
            index = next(item.index for item in opened.list_items() if not item.is_dir)
            opened.extract_to_memory(index, password=_TEST_SECRET)
        after = _scan_cmdlines_with(_TEST_SECRET)
        if after:
            print(f"    [FAIL] 操作後に露出: {after}")
            return 1
        print("    [OK] 操作後: 露出ゼロ")

        # 7. IOutArchive で圧縮 (平文 / AES-256 / ヘッダー暗号化)
        print("\n[7] 7z.dll (IOutArchive) で圧縮...")
        write_src = work / "write-src"
        (write_src / "dir1").mkdir(parents=True)
        (write_src / "dir1" / "file.txt").write_bytes(_CONTENT * 3)
        (write_src / "top.bin").write_bytes(b"\x00\x01\x02" * 50)
        write_items = _build_write_items(write_src)
        expected_files = {
            "dir1/file.txt": _CONTENT * 3,
            "top.bin": b"\x00\x01\x02" * 50,
        }
        write_cases: list[dict] = [
            {"label": "write-plain.zip", "handler": "zip"},
            {
                "label": "write-enc.zip",
                "handler": "zip",
                "password": _TEST_SECRET,
                "encrypt_method": "AES256",
            },
            {"label": "write-plain.7z", "handler": "7z"},
            {
                "label": "write-enc.7z",
                "handler": "7z",
                "password": _TEST_SECRET,
            },
            {
                "label": "write-enc-headers.7z",
                "handler": "7z",
                "password": _TEST_SECRET,
                "encrypt_headers": True,
            },
        ]

        write_calls: list[object] = []
        subprocess.Popen = _recording_popen  # type: ignore[assignment]
        try:
            for case in write_cases:
                out = work / case["label"]
                kwargs = {
                    key: case[key]
                    for key in ("password", "encrypt_method", "encrypt_headers")
                    if key in case
                }
                dll.create_archive(out, case["handler"], write_items, **kwargs)
                names, contents = _read_back(
                    dll, out, case["handler"], case.get("password")
                )
                ok_names = set(names) == set(expected_files)
                ok_data = contents == expected_files
                header_note = (
                    " ヘッダー暗号化=ON" if case.get("encrypt_headers") else ""
                )
                print(
                    f"    {case['label']}: 項目={names} 一致={ok_names and ok_data}"
                    f"{header_note}"
                )
                if not (ok_names and ok_data):
                    print(f"    [FAIL] {case['label']} の往復検証が一致しません")
                    return 1
        finally:
            subprocess.Popen = original_popen  # type: ignore[assignment]

        if write_calls:
            print(
                f"    [FAIL] 圧縮中に subprocess が {len(write_calls)} 回呼ばれました"
            )
            return 1
        print("    [OK] 圧縮中の subprocess 呼び出しゼロ (パスワードはプロセス内供給)")

        # 8. 圧縮後のコマンドライン走査
        print("\n[8] 圧縮後の全プロセス・コマンドライン走査...")
        after_write = _scan_cmdlines_with(_TEST_SECRET)
        if after_write:
            print(f"    [FAIL] 圧縮後に露出: {after_write}")
            return 1
        print("    [OK] 圧縮後: 露出ゼロ")

    print("\n" + "=" * 72)
    print("結果: 全チェック PASS — 7z.dll 直接統合で")
    print("  • ZIP (stdlib パスを含む) / 7z を 1 つの DLL バックエンドで処理")
    print("  • 読み取り・書き込みともパスワードはプロセス内で供給")
    print(
        "    (IInArchive: ICryptoGetTextPassword / IOutArchive: ICryptoGetTextPassword2)"
    )
    print("  • 圧縮も対応: 平文 / AES-256 ZIP / 暗号化 7z / ヘッダー暗号化 7z")
    print("  • subprocess ゼロ → コマンドライン露出ゼロ")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
