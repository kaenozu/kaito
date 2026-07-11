"""パストラバーサル、リンク、アーカイブ爆弾のセキュリティテスト。"""

from __future__ import annotations

import stat
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from kaito.domain.errors import ArchiveBombError, UnsafeArchiveError
from kaito.domain.models import (
    ArchiveEntry,
    ExtractionOptions,
    check_archive_safety,
    validate_entry_path,
)
from kaito.unzip import extract_all


def _entry(
    name: str,
    *,
    size: int = 1,
    compressed_size: int = 1,
    is_dir: bool = False,
    is_link: bool = False,
    link_target: str | None = None,
) -> ArchiveEntry:
    return ArchiveEntry(
        name=name,
        size=size,
        compressed_size=compressed_size,
        modified=datetime(2026, 1, 1),
        is_dir=is_dir,
        is_link=is_link,
        link_target=link_target,
    )


class TestPathValidation:
    @pytest.mark.parametrize(
        "name",
        [
            "../outside.txt",
            "..\\outside.txt",
            "a/b/../../../../etc/passwd",
            "/absolute.txt",
            "\\absolute.txt",
            "C:\\outside.txt",
            "\\\\server\\share\\file.txt",
            "..\\folder/../file.txt",
            "CON.txt",
            "NUL",
            "COM1",
            "LPT1.txt",
            "file.txt:Zone.Identifier",
            "file.txt:$DATA",
            "trailing-dot.",
            "trailing-space ",
            "bad\x00name",
            "",
        ],
    )
    def test_unsafe_names_are_rejected(self, name: str, tmp_path: Path) -> None:
        with pytest.raises(UnsafeArchiveError):
            validate_entry_path(name, tmp_path / "safe")

    @pytest.mark.parametrize(
        "name", ["file.txt", "sub/file.txt", "folder/", "日本語/資料.txt"]
    )
    def test_safe_names_remain_inside_destination(
        self, name: str, tmp_path: Path
    ) -> None:
        destination = tmp_path / "safe"
        target = validate_entry_path(name, destination)
        target.relative_to(destination.resolve())

    def test_archive_link_entry_is_rejected(self, tmp_path: Path) -> None:
        entries = [
            _entry(
                "link",
                size=0,
                compressed_size=0,
                is_link=True,
                link_target="../outside",
            )
        ]
        with pytest.raises(UnsafeArchiveError, match="リンク"):
            check_archive_safety(entries, ExtractionOptions(dest_dir=tmp_path / "out"))


class TestArchiveBombDetection:
    def test_normal_entries(self, tmp_path: Path) -> None:
        check_archive_safety(
            [_entry("a.txt", size=100, compressed_size=80)],
            ExtractionOptions(dest_dir=tmp_path / "out"),
        )

    def test_too_many_entries(self, tmp_path: Path) -> None:
        entries = [_entry(f"f{i}.txt") for i in range(101)]
        with pytest.raises(ArchiveBombError, match="エントリ数"):
            check_archive_safety(
                entries,
                ExtractionOptions(dest_dir=tmp_path / "out", max_entries=100),
            )

    def test_single_file_too_large(self, tmp_path: Path) -> None:
        with pytest.raises(ArchiveBombError, match="ファイルサイズ"):
            check_archive_safety(
                [_entry("big.bin", size=101, compressed_size=1)],
                ExtractionOptions(dest_dir=tmp_path / "out", max_file_size=100),
            )

    def test_total_size_too_large(self, tmp_path: Path) -> None:
        entries = [
            _entry("a.bin", size=60, compressed_size=40),
            _entry("b.bin", size=60, compressed_size=40),
        ]
        with pytest.raises(ArchiveBombError, match="合計展開サイズ"):
            check_archive_safety(
                entries,
                ExtractionOptions(
                    dest_dir=tmp_path / "out", max_file_size=100, max_total_size=100
                ),
            )

    def test_high_compression_ratio(self, tmp_path: Path) -> None:
        with pytest.raises(ArchiveBombError, match="圧縮率"):
            check_archive_safety(
                [_entry("bomb.bin", size=100_000, compressed_size=1)],
                ExtractionOptions(
                    dest_dir=tmp_path / "out",
                    max_file_size=200_000,
                    max_total_size=200_000,
                    max_compression_ratio=100.0,
                ),
            )

    def test_negative_size_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(UnsafeArchiveError, match="サイズ"):
            check_archive_safety(
                [_entry("bad.bin", size=-1, compressed_size=1)],
                ExtractionOptions(dest_dir=tmp_path / "out"),
            )


class TestZipExtractionSecurity:
    @staticmethod
    def _make_zip(tmp_path: Path, entries: list[tuple[str, bytes]]) -> Path:
        archive_path = tmp_path / "archive.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            for name, content in entries:
                archive.writestr(name, content)
        return archive_path

    @pytest.mark.parametrize(
        "entry_name",
        [
            "../outside.txt",
            "..\\outside.txt",
            "/absolute.txt",
            "C:\\drive.txt",
            "a/b/../../../../etc/passwd",
            "../../outside/evil.txt",
            "file.txt:Zone.Identifier",
            "CON.txt",
        ],
    )
    def test_unsafe_zip_cannot_escape(self, entry_name: str, tmp_path: Path) -> None:
        archive_path = self._make_zip(tmp_path, [(entry_name, b"evil")])
        destination = tmp_path / "out"
        with pytest.raises(UnsafeArchiveError):
            extract_all(archive_path, destination)
        assert not (tmp_path / "outside.txt").exists()
        assert not (tmp_path / "outside" / "evil.txt").exists()

    def test_directory_entry_traversal_is_rejected(self, tmp_path: Path) -> None:
        archive_path = self._make_zip(
            tmp_path,
            [("../../outside/", b""), ("../../outside/evil.txt", b"evil")],
        )
        with pytest.raises(UnsafeArchiveError):
            extract_all(archive_path, tmp_path / "out")
        assert not (tmp_path / "outside").exists()

    def test_zip_symlink_entry_is_rejected_without_os_symlink_privilege(
        self, tmp_path: Path
    ) -> None:
        archive_path = tmp_path / "symlink.zip"
        info = zipfile.ZipInfo("outside-link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr(info, "../outside")

        destination = tmp_path / "out"
        with pytest.raises(UnsafeArchiveError, match="リンク"):
            extract_all(archive_path, destination)
        assert not destination.exists()

    def test_normal_file_extracts(self, tmp_path: Path) -> None:
        archive_path = self._make_zip(
            tmp_path, [("safe_file.txt", b"data"), ("sub/safe.txt", b"nested")]
        )
        destination = tmp_path / "out"
        extract_all(archive_path, destination)
        assert (destination / "safe_file.txt").read_bytes() == b"data"
        assert (destination / "sub/safe.txt").read_bytes() == b"nested"
