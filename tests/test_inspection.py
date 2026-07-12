from datetime import datetime
from pathlib import Path

from kaito.archive.inspection import (
    expand_selected_members,
    filter_entries,
    inspect_archive,
)
from kaito.domain.models import ArchiveEntry, ArchiveInfo, SafetyLimits


def _entry(
    name: str,
    *,
    size: int = 10,
    compressed: int = 5,
    is_dir: bool = False,
    encrypted: bool = False,
    is_link: bool = False,
) -> ArchiveEntry:
    return ArchiveEntry(
        name=name,
        size=size,
        compressed_size=compressed,
        modified=datetime(2026, 1, 1),
        is_dir=is_dir,
        is_encrypted=encrypted,
        is_link=is_link,
    )


def test_safe_archive_report() -> None:
    info = ArchiveInfo(Path("safe.zip"), [_entry("docs/readme.txt")], False, "zip")

    report = inspect_archive(info, SafetyLimits())

    assert report.status == "safe"
    assert report.can_extract
    assert report.file_count == 1
    assert report.compression_ratio == 2.0


def test_executable_and_double_extension_warn() -> None:
    info = ArchiveInfo(
        Path("download.zip"),
        [_entry("photo.jpg.exe", size=100, compressed=50)],
        False,
        "zip",
    )

    report = inspect_archive(info, SafetyLimits())

    assert report.status == "warning"
    assert report.executable_count == 1
    assert {finding.code for finding in report.findings} >= {
        "executables",
        "double-extension",
    }


def test_unsafe_path_is_blocked() -> None:
    info = ArchiveInfo(Path("unsafe.zip"), [_entry("../escape.txt")], False, "zip")

    report = inspect_archive(info, SafetyLimits())

    assert report.status == "blocked"
    assert not report.can_extract


def test_filter_entries_supports_categories_and_globs() -> None:
    entries = [
        _entry("images/photo.png"),
        _entry("docs/report.pdf"),
        _entry("tools/setup.exe"),
        _entry("large.bin", size=101 * 1024 * 1024),
        _entry("secret.txt", encrypted=True),
    ]

    assert [item.name for item in filter_entries(entries, "*.png", "すべて")] == [
        "images/photo.png"
    ]
    assert [item.name for item in filter_entries(entries, "", "文書")] == [
        "docs/report.pdf",
        "secret.txt",
    ]
    assert [item.name for item in filter_entries(entries, "", "実行ファイル")] == [
        "tools/setup.exe"
    ]
    assert [item.name for item in filter_entries(entries, "", "大きいファイル")] == [
        "large.bin"
    ]
    assert [item.name for item in filter_entries(entries, "", "暗号化")] == [
        "secret.txt"
    ]


def test_expand_selected_directory_members() -> None:
    entries = [
        _entry("docs/", is_dir=True),
        _entry("docs/a.txt"),
        _entry("docs/nested/b.txt"),
        _entry("other.txt"),
    ]

    assert expand_selected_members(entries, ["docs/"]) == [
        "docs/",
        "docs/a.txt",
        "docs/nested/b.txt",
    ]
