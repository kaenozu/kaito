"""
tests/test_unzip.py
unzip.py のテスト (新アーキテクチャ対応)
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from kaito.unzip import (
    ARCHIVE_EXTENSIONS,
    ZipEntry,
    create_archive,
    extract,
    extract_all,
    extract_archive,
    is_supported,
    list_archive,
    list_entries,
    _validate_zip_member,
)
from kaito.domain.errors import (
    ExtractionFailedError,
    UnsupportedFormatError,
    UnsafeArchiveError,
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
        import zipfile

        z = tmp_dir / "encrypted.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("secret.txt", "data")
        raw = bytearray(z.read_bytes())
        patched = False
        for i in range(len(raw) - 4):
            if raw[i : i + 4] == b"PK\x01\x02":
                raw[i + 8] |= 0x01
                patched = True
                break
        assert patched, "central directory PK\\x01\\x02 not found"
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
        with pytest.raises(ExtractionFailedError):
            list_entries(bad)

    def test_nonexistent_file(self) -> None:
        with pytest.raises(ExtractionFailedError):
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
        dest = tmp_dir / "out"
        extract_all(normal_zip, dest, password="unused")
        assert (dest / "hello.txt").read_text() == "Hello World"

    def test_extract_dir_entries(
        self, zip_with_dir_entries: Path, tmp_dir: Path
    ) -> None:
        dest = tmp_dir / "out"
        extract_all(zip_with_dir_entries, dest)
        assert (dest / "folder").is_dir()
        assert (dest / "folder/a.txt").read_text() == "A"
        assert (dest / "empty_dir").is_dir()

    def test_extract_nonexistent_member(self, normal_zip: Path, tmp_dir: Path) -> None:
        dest = tmp_dir / "out"
        with pytest.raises(ExtractionFailedError):
            extract(normal_zip, dest, members=["nonexistent.txt"])

    def test_extract_overwrite(self, normal_zip: Path, tmp_dir: Path) -> None:
        dest = tmp_dir / "out"
        extract_all(normal_zip, dest)
        extract_all(normal_zip, dest)
        assert (dest / "hello.txt").read_text() == "Hello World"


class TestExtractEdgeCases:
    """extract のエッジケース"""

    def test_str_path(self, normal_zip: Path, tmp_dir: Path) -> None:
        extract_all(str(normal_zip), str(tmp_dir / "out"))
        assert (tmp_dir / "out" / "hello.txt").read_text() == "Hello World"

    def test_empty_zip(self, empty_zip: Path, tmp_dir: Path) -> None:
        dest = tmp_dir / "out"
        extract_all(empty_zip, dest)
        assert not dest.exists()


class TestPathTraversal:
    """パストラバーサル対策のテスト"""

    def make_zip_with_name(
        self, tmp_dir: Path, entry_name: str, content: bytes = b"data"
    ) -> Path:
        import zipfile

        path = tmp_dir / "evil.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr(entry_name, content)
        return path

    def test_normal_subfile(self, tmp_dir: Path) -> None:
        z = self.make_zip_with_name(tmp_dir, "sub/file.txt")
        dest = tmp_dir / "out"
        extract_all(z, dest)
        assert (dest / "sub/file.txt").read_text() == "data"

    def test_normal_folder_entry(self, tmp_dir: Path) -> None:
        import zipfile

        path = tmp_dir / "normal.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("folder/", "")
            zf.writestr("folder/a.txt", "A")
        dest = tmp_dir / "out"
        extract_all(path, dest)
        assert (dest / "folder/a.txt").read_text() == "A"

    def test_parent_traversal_slash(self, tmp_dir: Path) -> None:
        z = self.make_zip_with_name(tmp_dir, "../evil.txt")
        dest = tmp_dir / "out"
        with pytest.raises(UnsafeArchiveError, match="親ディレクトリ参照"):
            extract_all(z, dest)

    def test_parent_traversal_backslash(self, tmp_dir: Path) -> None:
        z = self.make_zip_with_name(tmp_dir, "..\\evil.txt")
        dest = tmp_dir / "out"
        with pytest.raises(UnsafeArchiveError, match="親ディレクトリ参照"):
            extract_all(z, dest)

    def test_absolute_path_slash(self, tmp_dir: Path) -> None:
        z = self.make_zip_with_name(tmp_dir, "/absolute.txt")
        dest = tmp_dir / "out"
        with pytest.raises(UnsafeArchiveError, match="絶対パス"):
            extract_all(z, dest)

    def test_windows_drive_path(self, tmp_dir: Path) -> None:
        z = self.make_zip_with_name(tmp_dir, "C:\\evil.txt")
        dest = tmp_dir / "out"
        with pytest.raises(UnsafeArchiveError, match="Windowsドライブパス"):
            extract_all(z, dest)

    def test_unc_path(self, tmp_dir: Path) -> None:
        z = self.make_zip_with_name(tmp_dir, "\\\\server\\share\\file.txt")
        dest = tmp_dir / "out"
        with pytest.raises(UnsafeArchiveError, match="(UNCパス|絶対パス)"):
            extract_all(z, dest)

    def test_empty_name(self, tmp_dir: Path) -> None:
        with pytest.raises(UnsafeArchiveError, match="空のエントリ名"):
            _validate_zip_member("", tmp_dir / "out")

    def test_deep_traversal(self, tmp_dir: Path) -> None:
        z = self.make_zip_with_name(tmp_dir, "a/b/../../../../etc/passwd")
        dest = tmp_dir / "out"
        with pytest.raises(UnsafeArchiveError, match="親ディレクトリ参照"):
            extract_all(z, dest)


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

    def test_list_rar(self, tmp_path: Path) -> None:
        """RARファイルの一覧取得 (7z CLIがなくてもエラーにならない)"""
        rar = tmp_path / "test.rar"
        rar.touch()
        with pytest.raises(ExtractionFailedError):
            list_archive(rar)

    def test_list_7z(self, tmp_path: Path) -> None:
        """7zファイルの一覧取得 (7z CLIがなくてもエラーにならない)"""
        sz = tmp_path / "test.7z"
        sz.touch()
        with pytest.raises(ExtractionFailedError):
            list_archive(sz)

    def test_list_unsupported(self, tmp_path: Path) -> None:
        f = tmp_path / "test.tar.gz"
        f.touch()
        with pytest.raises(UnsupportedFormatError):
            list_archive(f)


class TestCreateArchive:
    """create_archive のテスト"""

    def test_create_zip_from_files(self, tmp_dir: Path) -> None:
        src1 = tmp_dir / "a.txt"
        src1.write_text("AAA")
        src2 = tmp_dir / "b.txt"
        src2.write_text("BBB")
        output = tmp_dir / "out.zip"

        create_archive([src1, src2], output)

        assert output.exists()
        import zipfile

        with zipfile.ZipFile(output) as zf:
            names = zf.namelist()
            assert "a.txt" in names
            assert "b.txt" in names
            assert zf.read("a.txt") == b"AAA"
            assert zf.read("b.txt") == b"BBB"

    def test_create_zip_from_dir(self, tmp_dir: Path) -> None:
        src_dir = tmp_dir / "myfolder"
        src_dir.mkdir()
        (src_dir / "file1.txt").write_text("1")
        sub = src_dir / "sub"
        sub.mkdir()
        (sub / "file2.txt").write_text("2")
        output = tmp_dir / "out.zip"

        create_archive([src_dir], output)

        import zipfile

        with zipfile.ZipFile(output) as zf:
            names = zf.namelist()
            assert "myfolder/file1.txt" in names
            assert "myfolder/sub/file2.txt" in names

    def test_create_zip_progress(self, tmp_dir: Path) -> None:
        src1 = tmp_dir / "a.txt"
        src1.write_text("A")
        src2 = tmp_dir / "b.txt"
        src2.write_text("B")
        output = tmp_dir / "out.zip"

        calls: list[tuple[int, int, str]] = []

        def progress(cur: int, total: int, name: str = "") -> None:
            calls.append((cur, total, name))

        create_archive([src1, src2], output, on_progress=progress)
        assert len(calls) == 2
        assert calls[-1] == (2, 2, "b.txt")

    def test_create_unsupported_raises(self, tmp_dir: Path) -> None:
        src = tmp_dir / "a.txt"
        src.write_text("A")
        output = tmp_dir / "out.tar.gz"
        with pytest.raises(UnsupportedFormatError):
            create_archive([src], output)

    def test_create_rar_unsupported(self, tmp_dir: Path) -> None:
        """RAR作成は非対応"""
        src = tmp_dir / "a.txt"
        src.write_text("A")
        output = tmp_dir / "out.rar"
        with pytest.raises(UnsupportedFormatError, match="RAR"):
            create_archive([src], output)


class TestExtractArchive:
    """extract_archive のテスト"""

    def test_extract_zip(self, normal_zip: Path, tmp_dir: Path) -> None:
        dest = tmp_dir / "out"
        extract_archive(normal_zip, dest)
        assert (dest / "hello.txt").read_text() == "Hello World"

    def test_extract_rar(self, tmp_path: Path) -> None:
        rar = tmp_path / "test.rar"
        rar.touch()
        with pytest.raises(ExtractionFailedError):
            extract_archive(rar, tmp_path / "out")

    def test_extract_7z(self, tmp_path: Path) -> None:
        sz = tmp_path / "test.7z"
        sz.touch()
        with pytest.raises(ExtractionFailedError):
            extract_archive(sz, tmp_path / "out")

    def test_extract_unsupported(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.touch()
        with pytest.raises(UnsupportedFormatError, match="未対応"):
            extract_archive(f, tmp_path / "out")
