"""7z.dll 直接統合 PoC のテスト (Windows + bundled/7z.dll が前提)。

PoC の主張を回帰テストとして固定する:
  - 暗号化 ZIP / 7z を DLL (IInArchive) で一覧・展開できる
  - パスワードはプロセス内で供給され、subprocess を一切生まない
  - IOutArchive で平文 / 暗号化 ZIP・7z / ヘッダー暗号化 7z を圧縮できる
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
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
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return archive


def _create_encrypted_7z(directory: Path, mhe: bool = False) -> Path:
    """暗号化 7z を CLI で作成する (mhe=True で -mhe=on ヘッダー暗号化)。"""
    source = directory / ("mhe-src" if mhe else "7z-src")
    source.mkdir()
    (source / "secret.txt").write_bytes(_CONTENT)
    archive = directory / ("enc-headers.7z" if mhe else "encrypted.7z")
    cmd = [
        str(_SEVENZ),
        "a",
        f"-p{_TEST_SECRET}",
        str(archive),
        str(source / "*"),
        "-y",
        "-sccUTF-8",
    ]
    if mhe:
        cmd.insert(2, "-mhe=on")
    result = subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return archive


def _build_write_items(source: Path) -> list[dict]:
    """IOutArchive::UpdateItems 用のソース項目 (ディレクトリは末尾区切りなし)。"""
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


def _norm(name: str) -> str:
    """読み取り側が Windows では '\\' を返すため '/' に正規化する。"""
    return name.replace("\\", "/")


def _read_back(
    dll: SevenZipDll, path: Path, handler: str, password: str | None
) -> dict[str, bytes]:
    with dll.open_archive(path, handler, password=password) as opened:
        listing = opened.list_items()
    contents: dict[str, bytes] = {}
    for item in listing:
        if item.is_dir:
            continue
        with dll.open_archive(path, handler, password=password) as opened:
            contents[_norm(item.name)] = opened.extract_to_memory(
                item.index, password=password
            )
    return contents


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


def test_dll_opens_header_encrypted_7z_requires_password_at_open(
    tmp_path: Path,
) -> None:
    """ヘッダー暗号化 7z (-mhe=on) は Open 時パスワードが必須。

    パスワードなしで開くと一覧が空になる (7-Zip の仕様: エラーではなく
    0 項目)。Open コールバック経由でパスワードを供給すると一覧・展開できる。
    """
    archive_path = _create_encrypted_7z(tmp_path, mhe=True)
    dll = SevenZipDll(_DLL)

    with dll.open_archive(archive_path, "7z", password=None) as opened:
        assert opened.list_items() == []

    with dll.open_archive(archive_path, "7z", password=_TEST_SECRET) as opened:
        files = [item for item in opened.list_items() if not item.is_dir]
        assert [item.name for item in files] == ["secret.txt"]
        assert (
            opened.extract_to_memory(files[0].index, password=_TEST_SECRET) == _CONTENT
        )


def test_dll_open_callback_supplies_password_for_header_encryption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ヘッダー暗号化 7z の Open 時に Open コールバック経由でパスワードを供給する。

    データ暗号化のみの 7z は Open 中にパスワードを要求しない (Extract 時のみ)。
    ヘッダー暗号化 7z は Open フェーズで ICryptoGetTextPassword が呼ばれる
    ことを実測で検証する。
    """
    data_path = _create_encrypted_7z(tmp_path, mhe=False)
    mhe_path = _create_encrypted_7z(tmp_path, mhe=True)
    dll = SevenZipDll(_DLL)

    from sevenzip_dll import _CryptoPassword

    calls = {"count": 0}
    original = _CryptoPassword._crypto_get_text_password

    def recording(self: _CryptoPassword, this: int, password_out: int) -> int:
        calls["count"] += 1
        return original(self, this, password_out)

    monkeypatch.setattr(_CryptoPassword, "_crypto_get_text_password", recording)

    # 対比: データ暗号化のみ → Open 中は呼ばれない
    with dll.open_archive(data_path, "7z", password=_TEST_SECRET) as opened:
        assert calls["count"] == 0

    # ヘッダー暗号化 → Open 中に呼ばれる (Open コールバック経由)
    with dll.open_archive(mhe_path, "7z", password=_TEST_SECRET) as opened:
        assert calls["count"] == 1
        files = [item for item in opened.list_items() if not item.is_dir]
        assert (
            opened.extract_to_memory(files[0].index, password=_TEST_SECRET) == _CONTENT
        )


# --- IOutArchive (圧縮) ---


def _write_source(tmp_path: Path) -> Path:
    source = tmp_path / "src"
    (source / "dir1").mkdir(parents=True)
    (source / "dir1" / "file.txt").write_bytes(_CONTENT)
    (source / "top.bin").write_bytes(b"\x00\x01\x02" * 50)
    return source


def test_dll_creates_plain_and_encrypted_archives(tmp_path: Path) -> None:
    """IOutArchive で ZIP / 7z を圧縮し、DLL 読み取りで往復検証できる。"""
    items = _build_write_items(_write_source(tmp_path))
    dll = SevenZipDll(_DLL)
    expected = {"dir1/file.txt": _CONTENT, "top.bin": b"\x00\x01\x02" * 50}

    cases = [
        ("plain.zip", "zip", None),
        ("enc.zip", "zip", _TEST_SECRET),
        ("plain.7z", "7z", None),
        ("enc.7z", "7z", _TEST_SECRET),
    ]
    for name, handler, password in cases:
        kwargs: dict[str, object] = {}
        if password:
            kwargs["password"] = password
        if handler == "zip" and password:
            kwargs["encrypt_method"] = "AES256"
        out = tmp_path / name
        dll.create_archive(out, handler, items, **kwargs)
        assert _read_back(dll, out, handler, password) == expected


def test_dll_creates_header_encrypted_7z(tmp_path: Path) -> None:
    """ヘッダー暗号化 7z (-mhe=on 相当): パスワードなしでは一覧が空になる。"""
    items = _build_write_items(_write_source(tmp_path))
    dll = SevenZipDll(_DLL)
    out = tmp_path / "enc-headers.7z"
    dll.create_archive(out, "7z", items, password=_TEST_SECRET, encrypt_headers=True)

    with dll.open_archive(out, "7z", password=None) as opened:
        assert opened.list_items() == []
    assert _read_back(dll, out, "7z", _TEST_SECRET) == {
        "dir1/file.txt": _CONTENT,
        "top.bin": b"\x00\x01\x02" * 50,
    }


def test_dll_write_spawns_no_subprocess(tmp_path: Path) -> None:
    """圧縮中も subprocess.Popen が呼ばれない (パスワードはプロセス内供給)。"""
    items = _build_write_items(_write_source(tmp_path))
    dll = SevenZipDll(_DLL)

    with patch("subprocess.Popen", wraps=subprocess.Popen) as popen_mock:
        dll.create_archive(
            tmp_path / "enc.zip",
            "zip",
            items,
            password=_TEST_SECRET,
            encrypt_method="AES256",
        )
        dll.create_archive(tmp_path / "enc.7z", "7z", items, password=_TEST_SECRET)
    assert popen_mock.call_count == 0


def test_dll_created_archive_rejects_wrong_password(tmp_path: Path) -> None:
    """DLL で作成した暗号化 ZIP も誤パスワードを拒否する。"""
    items = _build_write_items(_write_source(tmp_path))
    dll = SevenZipDll(_DLL)
    out = tmp_path / "enc.zip"
    dll.create_archive(
        out, "zip", items, password=_TEST_SECRET, encrypt_method="AES256"
    )

    with dll.open_archive(out, "zip", password=_TEST_SECRET) as opened:
        index = next(item.index for item in opened.list_items() if not item.is_dir)
        with pytest.raises(DllPocError):
            opened.extract_to_memory(index, password="wrong-password")
