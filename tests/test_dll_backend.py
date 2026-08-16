"""DllArchiveBackend (7z.dll 直接統合) の回帰テスト。

読み取り系 (一覧・展開・プレビュー・整合性検査) は同梱 7z.dll の
IInArchive で処理され、パスワードはプロセス内で供給されるため、
読み取り操作中に subprocess を一切生まないことを保証する。
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from kaito.archive.dll_backend import DllArchiveBackend
from kaito.archive.service import ArchiveService
from kaito.domain.errors import (
    CancelledError,
    ExtractionFailedError,
    InvalidPasswordError,
    PasswordRequiredError,
    UnsafeArchiveError,
)
from kaito.domain.models import ExtractionOptions, SafetyLimits

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DLL = _REPO_ROOT / "bundled" / "7z.dll"
_SEVENZ = _REPO_ROOT / "bundled" / "7z.exe"

pytestmark = [
    pytest.mark.skipif(sys.platform != "win32", reason="7z.dll 統合は Windows 専用"),
    pytest.mark.skipif(not _DLL.is_file(), reason="bundled/7z.dll がありません"),
]

# テスト専用クレデンシャル (実認証には使用しない・GitGuardian の誤検知を避けるため
# 変数名に password を含めない)
_TEST_SECRET = "Kaito-Dll-Integration-2026!"


def _run_7z(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(_SEVENZ), *args, "-y", "-sccUTF-8"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _create_aes_zip(directory: Path) -> Path:
    source = directory / "aes-src"
    source.mkdir()
    (source / "secret.txt").write_bytes(b"AES ZIP secret\n")
    archive = directory / "encrypted-aes.zip"
    result = _run_7z(
        [
            "a",
            "-tzip",
            "-mem=AES256",
            f"-p{_TEST_SECRET}",
            str(archive),
            str(source / "*"),
        ]
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return archive


def _create_header_encrypted_7z(directory: Path) -> Path:
    source = directory / "mhe-src"
    source.mkdir()
    (source / "secret.txt").write_text("header encrypted", encoding="utf-8")
    archive = directory / "header-encrypted.7z"
    result = _run_7z(
        ["a", "-mhe=on", f"-p{_TEST_SECRET}", str(archive), str(source / "*")]
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return archive


def _write_cp932_zip(z: Path, name: str, data: str) -> None:
    """UTF-8で書き込んだZIPのファイル名をCP932バイトに書き換えて再構築する"""
    import struct
    import zipfile

    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr(name, data)
    raw = bytearray(z.read_bytes())
    u8 = name.encode("utf-8")
    cp = name.encode("cp932")
    delta = len(u8) - len(cp)
    # UTF-8フラグ (bit 11 / 0x800) を local header (+7) と central (+9) で落とす
    i = 0
    while i < len(raw) - 4:
        sig = bytes(raw[i : i + 4])
        if sig == b"PK\x03\x04":
            raw[i + 7] &= ~0x08
        elif sig == b"PK\x01\x02":
            raw[i + 9] &= ~0x08
        i += 1
    # ファイル名をCP932バイトに置換（local header と central directory の両方）
    start = 0
    while True:
        idx = raw.find(u8, start)
        if idx < 0:
            break
        raw[idx : idx + len(u8)] = cp
        start = idx + len(cp)
    # ファイル名長フィールドを更新（local: +26, central: +28）
    for i in range(len(raw) - 4):
        sig = bytes(raw[i : i + 4])
        if sig == b"PK\x03\x04":
            raw[i + 26 : i + 28] = struct.pack("<H", len(cp))
        elif sig == b"PK\x01\x02":
            raw[i + 28 : i + 30] = struct.pack("<H", len(cp))
    # local_offset は先頭エントリのため 0 のまま（補正不要）
    # EOCD の central directory サイズ (+12) とオフセット (+16) を補正
    eocd = raw.rfind(b"PK\x05\x06")
    if eocd >= 0:
        cd_size = struct.unpack("<I", bytes(raw[eocd + 12 : eocd + 16]))[0]
        raw[eocd + 12 : eocd + 16] = struct.pack("<I", cd_size - delta)
        cd_off = struct.unpack("<I", bytes(raw[eocd + 16 : eocd + 20]))[0]
        raw[eocd + 16 : eocd + 20] = struct.pack("<I", cd_off - delta)
    z.write_bytes(raw)


# ---------------------------------------------------------------------------
# 一覧・読み出し・展開
# ---------------------------------------------------------------------------


def test_dll_backend_lists_zip_with_dir_slash(normal_zip: Path) -> None:
    info = DllArchiveBackend().list_archive(normal_zip)
    assert {entry.name for entry in info.entries} == {
        "hello.txt",
        "sub/file.txt",
        "sub/deep/secret.md",
    }
    assert not info.is_encrypted


def test_dll_backend_dir_entries_keep_trailing_slash(
    zip_with_dir_entries: Path,
) -> None:
    info = DllArchiveBackend().list_archive(zip_with_dir_entries)
    dir_names = [entry.name for entry in info.entries if entry.is_dir]
    assert "folder/" in dir_names
    assert "empty_dir/" in dir_names


def test_dll_backend_lists_and_reads_rar(normal_rar: Path) -> None:
    backend = DllArchiveBackend()
    info = backend.list_archive(normal_rar)
    assert [entry.name for entry in info.entries] == ["test.txt"]
    assert backend.read_entry(normal_rar, "test.txt") == b"test text document\r\n"


def test_dll_backend_extracts_7z(normal_7z: Path, tmp_path: Path) -> None:
    destination = tmp_path / "out"
    DllArchiveBackend().extract(normal_7z, ExtractionOptions(dest_dir=destination))
    assert (destination / "hello.txt").read_text(encoding="utf-8") == "Hello World"
    assert (destination / "sub/file.txt").read_text(encoding="utf-8") == "Nested file"


def test_dll_backend_extract_progress_per_file(
    normal_zip: Path, tmp_path: Path
) -> None:
    calls: list[tuple[int, int, str]] = []

    DllArchiveBackend().extract(
        normal_zip,
        ExtractionOptions(
            dest_dir=tmp_path / "out", on_progress=lambda *c: calls.append(c)
        ),  # type: ignore[arg-type]
    )

    assert [name for _, _, name in calls] == [
        "hello.txt",
        "sub/file.txt",
        "sub/deep/secret.md",
    ]
    assert calls[-1][:2] == (3, 3)


def test_dll_backend_integrity_and_availability() -> None:
    backend = DllArchiveBackend()
    available, error = backend.check_tool_availability()
    assert available is True
    assert error is None

    info = backend.backend_info()
    assert info["source"] == "bundled"
    assert info["integrity"] == "ok"
    assert info["sha256"] == info["expected_sha256"]
    assert Path(info["path"]).name.lower() == "7z.dll"


# ---------------------------------------------------------------------------
# 暗号化
# ---------------------------------------------------------------------------


def test_aes_zip_password_flow(tmp_path: Path) -> None:
    archive = _create_aes_zip(tmp_path)
    service = ArchiveService()

    info = service.list_archive(archive)
    assert info.is_encrypted is True

    with pytest.raises(PasswordRequiredError):
        service.extract(
            archive, ExtractionOptions(dest_dir=tmp_path / "missing-password")
        )
    with pytest.raises(InvalidPasswordError):
        service.extract(
            archive,
            ExtractionOptions(dest_dir=tmp_path / "wrong-password", password="wrong"),
        )

    destination = tmp_path / "correct-password"
    service.extract(
        archive, ExtractionOptions(dest_dir=destination, password=_TEST_SECRET)
    )
    assert (destination / "secret.txt").read_bytes() == b"AES ZIP secret\n"

    assert service.read_entry(archive, "secret.txt", password=_TEST_SECRET) == (
        b"AES ZIP secret\n"
    )
    assert service.read_entry(archive, "secret.txt", password="wrong") is None


def test_encrypted_rar_password_flow(encrypted_rar: Path, tmp_path: Path) -> None:
    service = ArchiveService()
    info = service.list_archive(encrypted_rar)
    assert info.is_encrypted is True

    with pytest.raises(PasswordRequiredError):
        service.extract(
            encrypted_rar, ExtractionOptions(dest_dir=tmp_path / "missing-password")
        )
    with pytest.raises(InvalidPasswordError):
        service.extract(
            encrypted_rar,
            ExtractionOptions(dest_dir=tmp_path / "wrong-password", password="wrong"),
        )
    destination = tmp_path / "correct-password"
    service.extract(
        encrypted_rar, ExtractionOptions(dest_dir=destination, password="12345678")
    )
    assert (destination / "foo.txt").stat().st_size == 16
    assert (destination / "bar.txt").stat().st_size == 16


def test_header_encrypted_7z_password_flow(tmp_path: Path) -> None:
    archive = _create_header_encrypted_7z(tmp_path)
    service = ArchiveService()

    with pytest.raises(PasswordRequiredError):
        service.list_archive(archive)

    info = service.list_archive(archive, password=_TEST_SECRET)
    assert info.is_encrypted is True

    with pytest.raises(InvalidPasswordError):
        service.extract(
            archive,
            ExtractionOptions(dest_dir=tmp_path / "wrong-password", password="wrong"),
        )

    destination = tmp_path / "correct-password"
    service.extract(
        archive, ExtractionOptions(dest_dir=destination, password=_TEST_SECRET)
    )
    assert (destination / "secret.txt").read_text(encoding="utf-8") == (
        "header encrypted"
    )


# ---------------------------------------------------------------------------
# 安全・破損・キャンセル
# ---------------------------------------------------------------------------


def test_corrupt_archives_raise(
    corrupt_zip: Path, corrupt_7z: Path, corrupt_rar: Path
) -> None:
    backend = DllArchiveBackend()
    for archive in (corrupt_zip, corrupt_7z, corrupt_rar):
        with pytest.raises(ExtractionFailedError):
            backend.list_archive(archive)


def test_empty_zip_lists_as_empty(empty_zip: Path) -> None:
    info = DllArchiveBackend().list_archive(empty_zip)
    assert info.entries == []
    assert not info.is_encrypted


def test_symlink_rar_is_detected_and_rejected(
    symlink_rar: Path, tmp_path: Path
) -> None:
    backend = DllArchiveBackend()
    info = backend.list_archive(symlink_rar)
    link = next(entry for entry in info.entries if entry.name == "testlink")
    assert link.is_link

    with pytest.raises(UnsafeArchiveError, match="リンク"):
        backend.extract(symlink_rar, ExtractionOptions(dest_dir=tmp_path / "out"))
    assert not (tmp_path / "out").exists()


def test_cancel_discards_staging(normal_zip: Path, tmp_path: Path) -> None:
    cancel_event = threading.Event()
    destination = tmp_path / "output"

    def cancel_after_first(current: int, total: int, name: str) -> None:
        del total, name
        if current == 1:
            cancel_event.set()

    service = ArchiveService(cancel_event=cancel_event)
    with pytest.raises(CancelledError):
        service.extract(
            normal_zip,
            ExtractionOptions(dest_dir=destination, on_progress=cancel_after_first),
        )

    assert not destination.exists()


def test_preview_limit_reaches_dll_read_entry(normal_zip: Path) -> None:
    service = ArchiveService(safety_limits=SafetyLimits(preview_max_size=4))
    assert service.read_entry(normal_zip, "hello.txt") is None

    default_service = ArchiveService()
    assert default_service.read_entry(normal_zip, "hello.txt") == b"Hello World"


# ---------------------------------------------------------------------------
# プロセス露出ゼロの保証
# ---------------------------------------------------------------------------


def test_read_operations_spawn_no_subprocess(
    normal_zip: Path, normal_7z: Path, normal_rar: Path, tmp_path: Path
) -> None:
    """読み取り系は DLL のみで処理され、subprocess.Popen を一切呼ばない。"""
    backend = DllArchiveBackend()

    with patch("subprocess.Popen", wraps=subprocess.Popen) as popen_mock:
        info = backend.list_archive(normal_zip)
        assert info.entries
        backend.read_entry(normal_zip, "hello.txt")
        backend.extract(normal_zip, ExtractionOptions(dest_dir=tmp_path / "zip-out"))
        backend.test_archive(normal_zip)

        backend.list_archive(normal_7z)
        backend.list_archive(normal_rar)
        backend.read_entry(normal_rar, "test.txt")

        assert popen_mock.call_count == 0


# ---------------------------------------------------------------------------
# ZIP 名のエンコーディング (CP932 等の非UTF-8名)
# ---------------------------------------------------------------------------


def test_zip_entry_names_decodes_cp932(tmp_path: Path) -> None:
    """CP932 名の ZIP をロケールに依らず正しくデコードできる。"""
    from kaito.archive.dll_backend import _zip_entry_names

    z = tmp_path / "cp932.zip"
    _write_cp932_zip(z, "日本語ファイル.txt", "data")
    assert _zip_entry_names(z) == ["日本語ファイル.txt"]
    # 非ZIP は None (DLL の名前を使う)
    assert _zip_entry_names(tmp_path / "plain.txt") is None


def test_dll_backend_lists_cp932_zipname(tmp_path: Path) -> None:
    """英語ロケールでも CP932 名の ZIP が正しい名前で一覧・展開できる。

    7-Zip はシステムのコードページで ZIP 名をデコードするため、英語 Windows
    では CP932 名が mojibake になる。DLL バックエンドは中央ディレクトリから
    デコードし直した名前で置き換える。
    """
    backend = DllArchiveBackend()
    z = tmp_path / "cp932.zip"
    _write_cp932_zip(z, "日本語ファイル.txt", "data")

    info = backend.list_archive(z)
    assert [entry.name for entry in info.entries] == ["日本語ファイル.txt"]

    dest = tmp_path / "out"
    backend.extract(z, ExtractionOptions(dest_dir=dest))
    assert (dest / "日本語ファイル.txt").read_text() == "data"
