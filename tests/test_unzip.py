"""
tests/test_unzip.py
unzip.py のテスト
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from kaito.unzip import (
    ARCHIVE_EXTENSIONS,
    ZipEntry,
    extract,
    extract_all,
    extract_archive,
    is_supported,
    list_archive,
    list_entries,
)


class TestZipEntry:
    """ZipEntryデータクラスのテスト"""

    def test_fields(self) -> None:
        entry = ZipEntry(
            name="file.txt",
            size=100,
            compressed_size=80,
            modified=datetime(2026, 6, 2, 10, 0, 0),
            is_dir=False,
        )
        assert entry.name == "file.txt"
        assert entry.size == 100
        assert entry.compressed_size == 80
        assert entry.modified == datetime(2026, 6, 2, 10, 0, 0)
        assert not entry.is_dir

    def test_dir_entry(self) -> None:
        entry = ZipEntry(
            name="folder/",
            size=0,
            compressed_size=0,
            modified=datetime(2026, 1, 1, 0, 0, 0),
            is_dir=True,
        )
        assert entry.is_dir


class TestListEntries:
    """list_entries のテスト"""

    def test_normal_zip(self, normal_zip: Path) -> None:
        entries, encrypted = list_entries(normal_zip)
        assert not encrypted
        assert len(entries) == 3
        names = [e.name for e in entries]
        assert "hello.txt" in names
        assert "sub/file.txt" in names
        assert "sub/deep/secret.md" in names

    def test_zip_with_dir(self, zip_with_dir_entries: Path) -> None:
        entries, encrypted = list_entries(zip_with_dir_entries)
        assert not encrypted
        dir_names = [e.name for e in entries if e.is_dir]
        assert "folder/" in dir_names
        assert "empty_dir/" in dir_names

    def test_encrypted_flag(self, tmp_dir: Path) -> None:
        """central directoryのflag_bits(bit0)が立っているZIP"""
        import zipfile
        z = tmp_dir / "encrypted.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("secret.txt", "data")
        raw = bytearray(z.read_bytes())
        # central directory header (PK\x01\x02) の flag_bits(offset 8) を書き換え
        patched = False
        for i in range(len(raw) - 4):
            if raw[i:i+4] == b'PK\x01\x02':
                raw[i + 8] |= 0x01
                patched = True
                break
        assert patched, "central directory PK\x01\x02 not found"
        z.write_bytes(raw)
        entries, encrypted = list_entries(z)
        assert encrypted
        assert len(entries) == 1

    def test_empty_zip(self, empty_zip: Path) -> None:
        entries, encrypted = list_entries(empty_zip)
        assert not encrypted
        assert entries == []

    def test_bad_zip(self, tmp_dir: Path) -> None:
        bad = tmp_dir / "notazip.zip"
        bad.write_text("not a zip file")
        with pytest.raises(Exception):
            list_entries(bad)

    def test_nonexistent_file(self) -> None:
        with pytest.raises(FileNotFoundError):
            list_entries(Path("/nonexistent/path.zip"))


class TestExtract:
    """extract のテスト"""

    def test_extract_all(self, normal_zip: Path, tmp_dir: Path) -> None:
        dest = tmp_dir / "out"
        extract_all(normal_zip, dest)
        assert (dest / "hello.txt").read_text() == "Hello World"
        assert (dest / "sub/file.txt").read_text() == "Nested file"
        assert (dest / "sub/deep/secret.md").read_text() == "# Secret"

    def test_extract_with_members(self, normal_zip: Path, tmp_dir: Path) -> None:
        dest = tmp_dir / "out"
        extract(normal_zip, dest, members=["hello.txt"])
        assert (dest / "hello.txt").read_text() == "Hello World"
        assert not (dest / "sub/file.txt").exists()

    def test_extract_with_progress(self, normal_zip: Path, tmp_dir: Path) -> None:
        dest = tmp_dir / "out"
        calls: list[tuple[int, int]] = []

        def progress(current: int, total: int, _name: str = "") -> None:
            calls.append((current, total))

        extract_all(normal_zip, dest, on_progress=progress)
        assert len(calls) == 3
        assert calls[-1] == (3, 3)

    def test_extract_with_password(self, normal_zip: Path, tmp_dir: Path) -> None:
        """パスワード付きでも通常ZIPは解凍できる"""
        dest = tmp_dir / "out"
        extract_all(normal_zip, dest, password="unused")
        assert (dest / "hello.txt").read_text() == "Hello World"

    def test_extract_dir_entries(self, zip_with_dir_entries: Path, tmp_dir: Path) -> None:
        dest = tmp_dir / "out"
        extract_all(zip_with_dir_entries, dest)
        assert (dest / "folder").is_dir()
        assert (dest / "folder/a.txt").read_text() == "A"
        assert (dest / "empty_dir").is_dir()

    def test_extract_nonexistent_member(self, normal_zip: Path, tmp_dir: Path) -> None:
        """存在しないメンバーを指定するとKeyError"""
        dest = tmp_dir / "out"
        with pytest.raises(KeyError):
            extract(normal_zip, dest, members=["nonexistent.txt"])

    def test_extract_overwrite(self, normal_zip: Path, tmp_dir: Path) -> None:
        """上書き解凍ができる"""
        dest = tmp_dir / "out"
        extract_all(normal_zip, dest)
        extract_all(normal_zip, dest)  # 2回目もエラーなし
        assert (dest / "hello.txt").read_text() == "Hello World"


class TestExtractEdgeCases:
    """extract のエッジケース"""

    def test_str_path(self, normal_zip: Path, tmp_dir: Path) -> None:
        """文字列パスでも動作"""
        extract_all(str(normal_zip), str(tmp_dir / "out"))
        assert (tmp_dir / "out" / "hello.txt").read_text() == "Hello World"

    def test_empty_zip(self, empty_zip: Path, tmp_dir: Path) -> None:
        """空のZIPを解凍してもエラーにならない（destが作成されない）"""
        dest = tmp_dir / "out"
        extract_all(empty_zip, dest)
        assert not dest.exists()


class TestArchiveExtensions:
    """is_supported / ARCHIVE_EXTENSIONS のテスト"""

    def test_is_supported_zip(self) -> None:
        assert is_supported("test.zip")

    def test_is_supported_rar(self) -> None:
        assert is_supported("test.rar")

    def test_is_supported_7z(self) -> None:
        assert is_supported("test.7z")

    def test_is_supported_case_insensitive(self) -> None:
        assert is_supported("test.ZIP")
        assert is_supported("test.RAR")

    def test_is_supported_unsupported(self) -> None:
        assert not is_supported("test.tar.gz")
        assert not is_supported("test.txt")

    def test_archive_extensions_set(self) -> None:
        assert ARCHIVE_EXTENSIONS == {".zip", ".rar", ".7z"}


class TestListArchive:
    """list_archive のテスト"""

    def test_list_zip(self, normal_zip: Path) -> None:
        entries, encrypted = list_archive(normal_zip)
        assert len(entries) == 3
        assert not encrypted

    def test_list_rar_success(self, tmp_path: Path) -> None:
        rar = tmp_path / "test.rar"
        rar.touch()
        with (
            patch("kaito.unzip.patoolib.list_archive", return_value=["file.txt", "dir/"]),
        ):
            entries, encrypted = list_archive(rar)
            assert len(entries) == 2
            assert entries[0].name == "file.txt"
            assert entries[0].is_dir is False
            assert entries[1].name == "dir/"
            assert entries[1].is_dir
            assert not encrypted

    def test_list_patool_password_protected(self, tmp_path: Path) -> None:
        rar = tmp_path / "secret.rar"
        rar.touch()
        with patch("kaito.unzip.patoolib.list_archive", side_effect=RuntimeError("password required")):
            entries, encrypted = list_archive(rar)
            assert entries == []
            assert encrypted

    def test_list_rar_from_patool(self, tmp_path: Path) -> None:
        rar = tmp_path / "test.rar"
        rar.touch()
        with (
            pytest.raises(RuntimeError, match="アーカイブの一覧取得に失敗"),
        ):
            list_archive(rar)

    def test_list_unsupported(self, tmp_path: Path) -> None:
        f = tmp_path / "test.tar.gz"
        f.touch()
        with pytest.raises(ValueError):
            list_archive(f)


class TestExtractArchive:
    """extract_archive のテスト"""

    def test_extract_zip(self, normal_zip: Path, tmp_dir: Path) -> None:
        dest = tmp_dir / "out"
        extract_archive(normal_zip, dest)
        assert (dest / "hello.txt").read_text() == "Hello World"

    def test_extract_rar_from_patool(self, tmp_path: Path) -> None:
        rar = tmp_path / "test.rar"
        rar.touch()
        with (
            pytest.raises(RuntimeError, match="アーカイブの展開に失敗"),
        ):
            extract_archive(rar, tmp_path / "out")

    def test_extract_unsupported(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.touch()
        with pytest.raises(ValueError, match="未対応"):
            extract_archive(f, tmp_path / "out")
