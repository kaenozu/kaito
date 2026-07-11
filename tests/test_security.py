"""
tests/test_security.py
セキュリティテスト：パストラバーサル、アーカイブ爆弾対策を実ファイル展開で検証
"""

import zipfile
from pathlib import Path

import pytest

from kaito.domain.errors import UnsafeArchiveError, ArchiveBombError
from kaito.domain.models import (
    ArchiveEntry,
    ExtractionOptions,
    validate_entry_path,
    check_archive_safety,
)


class TestPathValidation:
    """validate_entry_path の網羅的テスト"""

    def _check(self, name: str, expect_safe: bool = True) -> None:
        dest = Path("C:/safe")
        if expect_safe:
            result = validate_entry_path(name, dest)
            assert result is not None
        else:
            with pytest.raises(UnsafeArchiveError):
                validate_entry_path(name, dest)

    def test_normal_file(self) -> None:
        self._check("file.txt")

    def test_normal_subdir(self) -> None:
        self._check("sub/file.txt")

    def test_normal_dir_entry(self) -> None:
        self._check("folder/")

    def test_traversal_slash(self) -> None:
        self._check("../outside.txt", expect_safe=False)

    def test_traversal_backslash(self) -> None:
        self._check("..\\outside.txt", expect_safe=False)

    def test_deep_traversal(self) -> None:
        self._check("a/b/../../../../etc/passwd", expect_safe=False)

    def test_absolute_slash(self) -> None:
        self._check("/absolute.txt", expect_safe=False)

    def test_absolute_backslash(self) -> None:
        self._check("\\absolute.txt", expect_safe=False)

    def test_windows_drive(self) -> None:
        self._check("C:\\outside.txt", expect_safe=False)

    def test_unc(self) -> None:
        self._check("\\\\server\\share\\file.txt", expect_safe=False)

    def test_mixed_separators(self) -> None:
        self._check("..\\folder/../file.txt", expect_safe=False)

    def test_reserved_name_con(self) -> None:
        self._check("CON.txt", expect_safe=False)

    def test_reserved_name_nul(self) -> None:
        self._check("NUL", expect_safe=False)

    def test_reserved_name_com1(self) -> None:
        self._check("COM1", expect_safe=False)

    def test_reserved_name_lpt1(self) -> None:
        self._check("LPT1.txt", expect_safe=False)

    def test_ads_normal(self) -> None:
        self._check("file.txt:Zone.Identifier", expect_safe=False)

    def test_ads_data(self) -> None:
        self._check("file.txt:$DATA", expect_safe=False)

    def test_empty_name(self) -> None:
        self._check("", expect_safe=False)

    def test_symlink_outside_skipped(self) -> None:
        """シンボリックリンクのテストは展開先解決で保護される"""
        # validate_entry_path の resolve() は symlink 先を追跡するため、
        # リンク先が展開先外にある場合は UnsafeArchiveError になる。
        # このテストはスキップ：Windowsのシンボリックリンク作成には特権が必要
        pytest.skip("symlink test requires admin/developer mode on Windows")


class TestArchiveBombDetection:
    """check_archive_safety の網羅的テスト"""

    def test_normal_entries(self) -> None:
        entries = [
            ArchiveEntry(
                name="a.txt", size=100, compressed_size=80, modified=..., is_dir=False
            )
        ]
        opts = ExtractionOptions(dest_dir=Path("."))
        check_archive_safety(entries, opts)  # should not raise

    def test_too_many_entries(self) -> None:
        entries = [
            ArchiveEntry(
                name=f"f{i}.txt", size=1, compressed_size=1, modified=..., is_dir=False
            )
            for i in range(100001)
        ]
        opts = ExtractionOptions(dest_dir=Path("."), max_entries=100000)
        with pytest.raises(ArchiveBombError, match="エントリ数"):
            check_archive_safety(entries, opts)

    def test_single_file_too_large(self) -> None:
        entries = [
            ArchiveEntry(
                name="big.bin",
                size=3 * 1024**3,
                compressed_size=100,
                modified=...,
                is_dir=False,
            )
        ]
        opts = ExtractionOptions(dest_dir=Path("."), max_file_size=2 * 1024**3)
        with pytest.raises(ArchiveBombError, match="ファイルサイズ"):
            check_archive_safety(entries, opts)

    def test_total_size_too_large(self) -> None:
        """合計サイズが上限を超えるケース（個別ファイルは上限内）"""
        # entries list kept for documentation but unused
        _ = [
            ArchiveEntry(
                name=f"a{i}.bin",
                size=3 * 1024**3,
                compressed_size=100,
                modified=...,
                is_dir=False,
            )
            for i in range(4)
        ]
        # 単一ファイル: 3GB < max_file_size (2GB?) → 3GB > 2GB, so goes to single file check
        # 代わりに小さいファイルを多数使う
        entries2 = [
            ArchiveEntry(
                name=f"b{i}.bin",
                size=500 * 1024**2,
                compressed_size=100,
                modified=...,
                is_dir=False,
            )
            for i in range(3)
        ]  # 合計 1500MB
        opts = ExtractionOptions(
            dest_dir=Path("."),
            max_total_size=1000 * 1024**2,
            max_file_size=2000 * 1024**2,
        )
        with pytest.raises(ArchiveBombError):
            check_archive_safety(entries2, opts)

    def test_high_compression_ratio(self) -> None:
        """圧縮率が1000倍を超える場合（個別ファイルサイズは上限内）"""
        entries = [
            ArchiveEntry(
                name="bomb.bin",
                size=500_000_000,
                compressed_size=1_000,
                modified=...,
                is_dir=False,
            )
        ]
        opts = ExtractionOptions(
            dest_dir=Path("."),
            max_compression_ratio=1000.0,
            max_file_size=2 * 1024**3,
        )
        with pytest.raises(ArchiveBombError, match="圧縮率"):
            check_archive_safety(entries, opts)


class TestPathTraversalInExtract:
    """実際の展開処理を通したパストラバーサル対策のテスト"""

    def _make_zip_with(
        self, tmp_dir: Path, entry_name: str, content: bytes = b"data"
    ) -> Path:
        path = tmp_dir / "evil.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr(entry_name, content)
        return path

    def test_traversal_slash(self, tmp_dir: Path) -> None:
        z = self._make_zip_with(tmp_dir, "../outside.txt")
        dest = tmp_dir / "out"
        from kaito.unzip import extract_all

        with pytest.raises(UnsafeArchiveError):
            extract_all(z, dest)
        # 確認: 展開先外にファイルが作成されていない
        assert not (tmp_dir / "outside.txt").exists()

    def test_traversal_backslash(self, tmp_dir: Path) -> None:
        z = self._make_zip_with(tmp_dir, "..\\outside.txt")
        dest = tmp_dir / "out"
        from kaito.unzip import extract_all

        with pytest.raises(UnsafeArchiveError):
            extract_all(z, dest)
        assert not (tmp_dir / "outside.txt").exists()

    def test_absolute_path(self, tmp_dir: Path) -> None:
        z = self._make_zip_with(tmp_dir, "/absolute.txt")
        dest = tmp_dir / "out"
        from kaito.unzip import extract_all

        with pytest.raises(UnsafeArchiveError):
            extract_all(z, dest)

    def test_windows_drive(self, tmp_dir: Path) -> None:
        z = self._make_zip_with(tmp_dir, "C:\\drive.txt")
        dest = tmp_dir / "out"
        from kaito.unzip import extract_all

        with pytest.raises(UnsafeArchiveError):
            extract_all(z, dest)

    def test_deep_traversal(self, tmp_dir: Path) -> None:
        z = self._make_zip_with(tmp_dir, "a/b/../../../../etc/passwd")
        dest = tmp_dir / "out"
        from kaito.unzip import extract_all

        with pytest.raises(UnsafeArchiveError):
            extract_all(z, dest)
        # 確認: 展開先外に作成されていない
        assert not (dest / "etc").exists()

    def test_normal_file_extracts(self, tmp_dir: Path) -> None:
        """通常ファイルは安全に展開される"""
        z = self._make_zip_with(tmp_dir, "safe_file.txt")
        dest = tmp_dir / "out"
        from kaito.unzip import extract_all

        extract_all(z, dest)
        assert (dest / "safe_file.txt").read_text() == "data"

    def test_normal_subdir(self, tmp_dir: Path) -> None:
        """通常のサブディレクトリは安全に展開される"""
        z = self._make_zip_with(tmp_dir, "sub/safe.txt")
        dest = tmp_dir / "out"
        from kaito.unzip import extract_all

        extract_all(z, dest)
        assert (dest / "sub/safe.txt").read_text() == "data"

    def test_dir_entry_with_traversal(self, tmp_dir: Path) -> None:
        """ディレクトリエントリを使ったZip Slip"""
        import zipfile

        path = tmp_dir / "dir_slip.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("../../outside/", "")
            zf.writestr("../../outside/evil.txt", "evil")
        dest = tmp_dir / "out"
        from kaito.unzip import extract_all

        with pytest.raises(UnsafeArchiveError):
            extract_all(path, dest)
        assert not (tmp_dir / "outside" / "evil.txt").exists()
