"""7z.dll 直接統合 PoC のテスト (Windows + bundled/7z.dll が前提)。

PoC の主張を回帰テストとして固定する:
  - 暗号化 ZIP / 7z を DLL (IInArchive) で一覧・展開できる
  - パスワードはプロセス内で供給され、subprocess を一切生まない
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_POC_DIR = _REPO_ROOT / "tools" / "dll-poc"
_DLL = _REPO_ROOT / "bundled" / "7z.dll"
_SEVENZ = _REPO_ROOT / "bundled" / "7z.exe"

pytestmark = [
    pytest.mark.skipif(
        sys.platform != "win32", reason="7z.dll 統合 PoC は Windows 専用"
    ),
    pytest.mark.skipif(not _DLL.is_file(), reason="bundled/7z.dll がありません"),
]

sys.path.insert(0, str(_POC_DIR))
from sevenzip_dll import DllPocError, SevenZipDll  # noqa: E402

_TEST_SECRET = "Kaito-Dll-Poc-2026!"
_CONTENT = b"DLL PoC secret content\n"


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
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return archive


def test_dll_lists_and_extracts_encrypted_zip(tmp_path: Path) -> None:
    archive_path = _create_encrypted_zip(tmp_path)
    dll = SevenZipDll(_DLL)

    with dll.open_archive(archive_path, "zip", password=_TEST_SECRET) as opened:
        items = opened.list_items()
        files = [item for item in items if not item.is_dir]
        assert [item.name for item in files] == ["secret.txt"]
        assert files[0].is_encrypted is True
        assert files[0].size == len(_CONTENT)
        assert (
            opened.extract_to_memory(files[0].index, password=_TEST_SECRET) == _CONTENT
        )


def test_dll_extracts_encrypted_7z(encrypted_7z: Path) -> None:
    dll = SevenZipDll(_DLL)

    with dll.open_archive(encrypted_7z, "7z", password="secret123") as opened:
        items = opened.list_items()
        files = [item for item in items if not item.is_dir]
        assert [item.name for item in files] == ["secret.txt"]
        assert (
            opened.extract_to_memory(files[0].index, password="secret123")
            == b"Secret Data"
        )


def test_dll_rejects_wrong_password(tmp_path: Path) -> None:
    archive_path = _create_encrypted_zip(tmp_path)
    dll = SevenZipDll(_DLL)

    with dll.open_archive(archive_path, "zip", password=_TEST_SECRET) as opened:
        index = next(item.index for item in opened.list_items() if not item.is_dir)
        with pytest.raises(DllPocError):
            opened.extract_to_memory(index, password="wrong-password")


def test_dll_operations_spawn_no_subprocess(tmp_path: Path) -> None:
    """DLL 操作中は subprocess.Popen が一度も呼ばれない (プロセスを生まない)。"""
    archive_path = _create_encrypted_zip(tmp_path)
    dll = SevenZipDll(_DLL)

    with patch("subprocess.Popen", wraps=subprocess.Popen) as popen_mock:
        with dll.open_archive(archive_path, "zip", password=_TEST_SECRET) as opened:
            items = opened.list_items()
            index = next(item.index for item in items if not item.is_dir)
            opened.extract_to_memory(index, password=_TEST_SECRET)
        assert popen_mock.call_count == 0


def test_dll_handler_discovery() -> None:
    """フォーマット名からハンドラ CLSID を解決できる (zip / 7z)。"""
    dll = SevenZipDll(_DLL)
    assert dll.find_handler_clsid("zip") is not None
    assert dll.find_handler_clsid("7z") is not None
    with pytest.raises(DllPocError):
        dll.find_handler_clsid("not-a-real-format")
