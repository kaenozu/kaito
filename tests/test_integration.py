"""アーカイブ処理の実ファイル統合テスト。"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from kaito.archive.service import ArchiveService
from kaito.domain.errors import (
    ExtractionFailedError,
    InvalidPasswordError,
    PasswordRequiredError,
    UnsafeArchiveError,
    UnsupportedFormatError,
)
from kaito.domain.models import CompressionOptions, ExtractionOptions


class TestZipIntegration:
    def test_list(self, normal_zip: Path) -> None:
        info = ArchiveService().list_archive(normal_zip)
        assert len(info.entries) == 3
        assert {entry.name for entry in info.entries} >= {"hello.txt", "sub/file.txt"}
        assert not info.is_encrypted

    def test_extract_all(self, normal_zip: Path, tmp_dir: Path) -> None:
        destination = tmp_dir / "out"
        ArchiveService().extract(normal_zip, ExtractionOptions(dest_dir=destination))
        assert (destination / "sub/deep/secret.md").read_text(encoding="utf-8") == "# Secret"

    def test_extract_members(self, normal_zip: Path, tmp_dir: Path) -> None:
        destination = tmp_dir / "out"
        ArchiveService().extract(
            normal_zip,
            ExtractionOptions(dest_dir=destination, members=["hello.txt"]),
        )
        assert (destination / "hello.txt").read_text(encoding="utf-8") == "Hello World"
        assert not (destination / "sub").exists()

    def test_compress(self, tmp_dir: Path) -> None:
        source = tmp_dir / "data.txt"
        source.write_text("test data", encoding="utf-8")
        output = tmp_dir / "out.zip"
        ArchiveService().create(CompressionOptions(sources=[source], output_path=output))
        with zipfile.ZipFile(output) as archive:
            assert archive.read("data.txt") == b"test data"

    def test_empty_zip(self, empty_zip: Path) -> None:
        assert ArchiveService().list_archive(empty_zip).entries == []

    def test_corrupt_zip(self, corrupt_zip: Path) -> None:
        with pytest.raises(ExtractionFailedError):
            ArchiveService().list_archive(corrupt_zip)

    def test_unsupported_format(self, tmp_dir: Path) -> None:
        path = tmp_dir / "test.txt"
        path.write_text("plain text", encoding="utf-8")
        with pytest.raises(UnsupportedFormatError):
            ArchiveService().list_archive(path)


class Test7zIntegration:
    def test_list(self, normal_7z: Path) -> None:
        info = ArchiveService().list_archive(normal_7z)
        assert {entry.name for entry in info.entries} >= {"hello.txt", "sub/file.txt"}
        assert not info.is_encrypted

    def test_extract(self, normal_7z: Path, tmp_dir: Path) -> None:
        destination = tmp_dir / "out"
        ArchiveService().extract(normal_7z, ExtractionOptions(dest_dir=destination))
        assert (destination / "hello.txt").read_text(encoding="utf-8") == "Hello World"

    def test_encrypted_list(self, encrypted_7z: Path) -> None:
        info = ArchiveService().list_archive(encrypted_7z)
        assert info.is_encrypted

    def test_encrypted_extract(self, encrypted_7z: Path, tmp_dir: Path) -> None:
        destination = tmp_dir / "out"
        ArchiveService().extract(
            encrypted_7z,
            ExtractionOptions(dest_dir=destination, password="secret123"),
        )
        assert (destination / "secret.txt").read_text(encoding="utf-8") == "Secret Data"

    def test_encrypted_wrong_password(self, encrypted_7z: Path, tmp_dir: Path) -> None:
        with pytest.raises(InvalidPasswordError):
            ArchiveService().extract(
                encrypted_7z,
                ExtractionOptions(dest_dir=tmp_dir / "wrong", password="wrongpass"),
            )

    def test_compress(self, tmp_dir: Path) -> None:
        source = tmp_dir / "7zdata.txt"
        source.write_text("7z test data", encoding="utf-8")
        output = tmp_dir / "out.7z"
        ArchiveService().create(CompressionOptions(sources=[source], output_path=output))
        assert output.is_file()
        assert {entry.name for entry in ArchiveService().list_archive(output).entries} == {
            "7zdata.txt"
        }

    def test_encrypted_create_is_really_encrypted(self, tmp_dir: Path) -> None:
        source = tmp_dir / "secret.txt"
        source.write_text("created encrypted data", encoding="utf-8")
        output = tmp_dir / "encrypted-created.7z"
        service = ArchiveService()
        service.create(
            CompressionOptions(
                sources=[source], output_path=output, password="create-secret"
            )
        )

        info = service.list_archive(output, password="create-secret")
        assert info.is_encrypted
        with pytest.raises((InvalidPasswordError, PasswordRequiredError)):
            service.extract(
                output,
                ExtractionOptions(dest_dir=tmp_dir / "no-password"),
            )
        with pytest.raises(InvalidPasswordError):
            service.extract(
                output,
                ExtractionOptions(dest_dir=tmp_dir / "wrong-password", password="bad"),
            )
        destination = tmp_dir / "correct-password"
        service.extract(
            output,
            ExtractionOptions(dest_dir=destination, password="create-secret"),
        )
        assert (destination / "secret.txt").read_text(encoding="utf-8") == (
            "created encrypted data"
        )

    def test_japanese_filenames(self, japanese_7z: Path, tmp_dir: Path) -> None:
        service = ArchiveService()
        info = service.list_archive(japanese_7z)
        assert any("日本語" in entry.name for entry in info.entries)
        destination = tmp_dir / "out"
        service.extract(japanese_7z, ExtractionOptions(dest_dir=destination))
        assert (destination / "日本語.txt").is_file()

    def test_corrupt_7z(self, corrupt_7z: Path) -> None:
        with pytest.raises(ExtractionFailedError):
            ArchiveService().list_archive(corrupt_7z)


class TestRarIntegration:
    """libarchiveの再配布可能な実RAR fixtureを7-Zipで検証する。"""

    def test_list_real_rar(self, normal_rar: Path) -> None:
        info = ArchiveService().list_archive(normal_rar)
        assert info.format_name == "rar"
        assert [entry.name for entry in info.entries] == ["test.txt"]
        assert info.entries[0].size == 20
        assert not info.is_encrypted

    def test_extract_real_rar(self, normal_rar: Path, tmp_dir: Path) -> None:
        destination = tmp_dir / "out"
        ArchiveService().extract(normal_rar, ExtractionOptions(dest_dir=destination))
        assert (destination / "test.txt").read_bytes() == b"test text document\r\n"

    def test_encrypted_rar_list(self, encrypted_rar: Path) -> None:
        info = ArchiveService().list_archive(encrypted_rar)
        assert {entry.name for entry in info.entries} == {"foo.txt", "bar.txt"}
        assert info.is_encrypted
        assert all(entry.size == 16 for entry in info.entries)

    def test_encrypted_rar_requires_password(
        self, encrypted_rar: Path, tmp_dir: Path
    ) -> None:
        with pytest.raises(PasswordRequiredError):
            ArchiveService().extract(
                encrypted_rar, ExtractionOptions(dest_dir=tmp_dir / "no-password")
            )

    def test_encrypted_rar_wrong_password(
        self, encrypted_rar: Path, tmp_dir: Path
    ) -> None:
        with pytest.raises(InvalidPasswordError):
            ArchiveService().extract(
                encrypted_rar,
                ExtractionOptions(dest_dir=tmp_dir / "wrong", password="wrong"),
            )

    def test_encrypted_rar_extracts_with_correct_password(
        self, encrypted_rar: Path, tmp_dir: Path
    ) -> None:
        destination = tmp_dir / "correct"
        ArchiveService().extract(
            encrypted_rar,
            ExtractionOptions(dest_dir=destination, password="12345678"),
        )
        assert (destination / "foo.txt").stat().st_size == 16
        assert (destination / "bar.txt").stat().st_size == 16

    def test_rar_link_entry_is_rejected(
        self, symlink_rar: Path, tmp_dir: Path
    ) -> None:
        service = ArchiveService()
        info = service.list_archive(symlink_rar)
        link = next(entry for entry in info.entries if entry.name == "testlink")
        assert link.is_link
        assert link.link_target == "test.txt"

        destination = tmp_dir / "link-out"
        with pytest.raises(UnsafeArchiveError, match="リンク"):
            service.extract(symlink_rar, ExtractionOptions(dest_dir=destination))
        assert not destination.exists()

    def test_create_rar_not_supported(self, tmp_dir: Path) -> None:
        source = tmp_dir / "a.txt"
        source.write_text("data", encoding="utf-8")
        with pytest.raises(UnsupportedFormatError, match="RAR"):
            ArchiveService().create(
                CompressionOptions(sources=[source], output_path=tmp_dir / "out.rar")
            )
        assert not (tmp_dir / "out.rar").exists()

    def test_corrupt_rar(self, corrupt_rar: Path) -> None:
        with pytest.raises(ExtractionFailedError):
            ArchiveService().list_archive(corrupt_rar)

    def test_rar_create_not_in_filetypes(self) -> None:
        assert not ArchiveService().is_creation_supported(Path("test.rar"))
