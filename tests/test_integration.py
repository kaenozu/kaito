"""
tests/test_integration.py
アーカイブ処理の統合テスト（実7-Zipが必要なテストを含む）
実際の展開結果を検証し、単体テストではカバーできない統合動作を確認する。
"""

from pathlib import Path
from typing import Optional

import pytest

from kaito.archive.service import ArchiveService
from kaito.archive.sevenzip_backend import SEVENZIP_VERSION
from kaito.domain.errors import (
    ExtractionFailedError,
    InvalidPasswordError,
    PasswordRequiredError,
    UnsupportedFormatError,
)
from kaito.domain.models import ArchiveEntry, ExtractionOptions


# =========================================================
# ZIP統合テスト（標準ライブラリのみ、常に実行可能）
# =========================================================


class TestZipIntegration:
    """ZIP: 一覧、展開、圧縮の実ファイル統合テスト"""

    def test_list(self, normal_zip: Path) -> None:
        svc = ArchiveService()
        info = svc.list_archive(normal_zip)
        assert len(info.entries) == 3
        names = [e.name for e in info.entries]
        assert "hello.txt" in names
        assert "sub/file.txt" in names
        assert not info.is_encrypted

    def test_extract_all(self, normal_zip: Path, tmp_dir: Path) -> None:
        svc = ArchiveService()
        opts = ExtractionOptions(dest_dir=tmp_dir / "out")
        svc.extract(normal_zip, opts)
        assert (tmp_dir / "out/sub/deep/secret.md").read_text() == "# Secret"

    def test_extract_members(self, normal_zip: Path, tmp_dir: Path) -> None:
        svc = ArchiveService()
        opts = ExtractionOptions(dest_dir=tmp_dir / "out", members=["hello.txt"])
        svc.extract(normal_zip, opts)
        assert (tmp_dir / "out/hello.txt").read_text() == "Hello World"
        assert not (tmp_dir / "out/sub").exists()

    def test_compress(self, tmp_dir: Path) -> None:
        src = tmp_dir / "data.txt"
        src.write_text("test data")
        out = tmp_dir / "out.zip"
        svc = ArchiveService()
        from kaito.domain.models import CompressionOptions

        opts = CompressionOptions(sources=[src], output_path=out)
        svc.create(opts)
        assert out.exists()
        import zipfile

        with zipfile.ZipFile(out) as zf:
            assert zf.read("data.txt") == b"test data"

    def test_empty_zip(self, empty_zip: Path, tmp_dir: Path) -> None:
        svc = ArchiveService()
        info = svc.list_archive(empty_zip)
        assert info.entries == []

    def test_corrupt_zip(self, corrupt_zip: Path) -> None:
        svc = ArchiveService()
        with pytest.raises(ExtractionFailedError):
            svc.list_archive(corrupt_zip)

    def test_unsupported_format(self, tmp_dir: Path) -> None:
        f = tmp_dir / "test.txt"
        f.write_text("plain text")
        svc = ArchiveService()
        with pytest.raises(UnsupportedFormatError):
            svc.list_archive(f)


# =========================================================
# 7z統合テスト（7-Zipが必要）
# =========================================================


@pytest.mark.skipif(
    not Path("C:/Program Files/7-Zip/7z.exe").exists(),
    reason="7-Zip not installed",
)
class Test7zIntegration:
    """7z: 一覧、展開、圧縮の実ファイル統合テスト"""

    def test_list(self, normal_7z: Path) -> None:
        svc = ArchiveService()
        info = svc.list_archive(normal_7z)
        assert len(info.entries) >= 2
        names = [e.name for e in info.entries]
        assert "hello.txt" in names
        assert not info.is_encrypted

    def test_extract(self, normal_7z: Path, tmp_dir: Path) -> None:
        svc = ArchiveService()
        opts = ExtractionOptions(dest_dir=tmp_dir / "out")
        svc.extract(normal_7z, opts)
        assert (tmp_dir / "out/hello.txt").read_text() == "Hello World"

    def test_encrypted_list(self, encrypted_7z: Path) -> None:
        """暗号化7zの一覧取得（パスワードなしでも一覧は取得可能、暗号化フラグが立つ）"""
        svc = ArchiveService()
        info = svc.list_archive(encrypted_7z)
        assert info.is_encrypted

    def test_encrypted_extract(self, encrypted_7z: Path, tmp_dir: Path) -> None:
        svc = ArchiveService()
        opts = ExtractionOptions(dest_dir=tmp_dir / "out", password="secret123")
        svc.extract(encrypted_7z, opts)
        assert (tmp_dir / "out/secret.txt").read_text() == "Secret Data"

    def test_encrypted_wrong_password(self, encrypted_7z: Path) -> None:
        svc = ArchiveService()
        opts = ExtractionOptions(dest_dir=Path("."), password="wrongpass")
        with pytest.raises(InvalidPasswordError):
            svc.extract(encrypted_7z, opts)

    def test_compress(self, tmp_dir: Path) -> None:
        src = tmp_dir / "7zdata.txt"
        src.write_text("7z test data")
        out = tmp_dir / "out.7z"
        svc = ArchiveService()
        from kaito.domain.models import CompressionOptions

        opts = CompressionOptions(sources=[src], output_path=out)
        svc.create(opts)
        assert out.exists()

    def test_japanese_filenames(self, japanese_7z: Path, tmp_dir: Path) -> None:
        svc = ArchiveService()
        info = svc.list_archive(japanese_7z)
        assert any("日本語" in e.name for e in info.entries)

        opts = ExtractionOptions(dest_dir=tmp_dir / "out")
        svc.extract(japanese_7z, opts)
        files = list((tmp_dir / "out").iterdir())
        assert any("日本語" in f.name for f in files)

    def test_corrupt_7z(self, corrupt_7z: Path) -> None:
        svc = ArchiveService()
        with pytest.raises(ExtractionFailedError):
            svc.list_archive(corrupt_7z)


# =========================================================
# RAR統合テスト（7-Zipが必要、RARは展開のみ）
# =========================================================


@pytest.mark.skipif(
    not Path("C:/Program Files/7-Zip/7z.exe").exists(),
    reason="7-Zip not installed",
)
class TestRarIntegration:
    """RAR: 一覧、展開（作成はできないことを確認）"""

    def test_list(self, normal_rar: Path) -> None:
        svc = ArchiveService()
        info = svc.list_archive(normal_rar)
        assert len(info.entries) >= 1
        assert not info.is_encrypted

    def test_extract(self, normal_rar: Path, tmp_dir: Path) -> None:
        svc = ArchiveService()
        opts = ExtractionOptions(dest_dir=tmp_dir / "out")
        svc.extract(normal_rar, opts)
        assert (tmp_dir / "out/readme.txt").read_text() == "RAR test file"

    def test_encrypted_list(self, encrypted_rar: Path) -> None:
        svc = ArchiveService()
        with pytest.raises(PasswordRequiredError):
            svc.list_archive(encrypted_rar)

    def test_encrypted_extract(self, encrypted_rar: Path, tmp_dir: Path) -> None:
        svc = ArchiveService()
        opts = ExtractionOptions(dest_dir=tmp_dir / "out", password="secret123")
        svc.extract(encrypted_rar, opts)
        assert (tmp_dir / "out/secret.txt").read_text() == "Secret RAR"

    def test_encrypted_wrong_password(self, encrypted_rar: Path) -> None:
        svc = ArchiveService()
        opts = ExtractionOptions(dest_dir=Path("."), password="wrongpass")
        with pytest.raises(InvalidPasswordError):
            svc.extract(encrypted_rar, opts)

    def test_create_rar_not_supported(self, tmp_dir: Path) -> None:
        svc = ArchiveService()
        from kaito.domain.models import CompressionOptions

        src = tmp_dir / "a.txt"
        src.write_text("data")
        opts = CompressionOptions(sources=[src], output_path=tmp_dir / "out.rar")
        with pytest.raises(UnsupportedFormatError, match="RAR"):
            svc.create(opts)

    def test_corrupt_rar(self, corrupt_rar: Path) -> None:
        svc = ArchiveService()
        with pytest.raises(ExtractionFailedError):
            svc.list_archive(corrupt_rar)

    def test_rar_create_not_in_filetypes(self) -> None:
        """RARが作成形式一覧に含まれていないことを確認"""
        svc = ArchiveService()
        assert not svc.is_creation_supported(Path("test.rar"))
