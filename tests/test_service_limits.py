"""ArchiveServiceが安全上限を必ず適用することを検証する。"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from kaito.archive.service import ArchiveService
from kaito.domain.errors import ArchiveBombError, UnsafeArchiveError
from kaito.domain.models import ExtractionOptions, SafetyLimits


def _make_zip(path: Path, name: str, payload: bytes) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, payload)
    return path


def test_service_caps_caller_file_size_limit(tmp_path: Path) -> None:
    archive_path = _make_zip(tmp_path / "large.zip", "payload.bin", b"x" * 11)
    service = ArchiveService(
        safety_limits=SafetyLimits(max_single_file_size=10, max_total_size=100)
    )

    with pytest.raises(ArchiveBombError, match="ファイルサイズ"):
        service.extract(
            archive_path,
            ExtractionOptions(
                dest_dir=tmp_path / "out",
                max_file_size=10_000,
                max_total_size=10_000,
            ),
        )


def test_caller_can_choose_stricter_limit_than_service(tmp_path: Path) -> None:
    archive_path = _make_zip(tmp_path / "strict.zip", "payload.bin", b"x" * 6)
    service = ArchiveService(
        safety_limits=SafetyLimits(max_single_file_size=100, max_total_size=100)
    )

    with pytest.raises(ArchiveBombError, match="ファイルサイズ"):
        service.extract(
            archive_path,
            ExtractionOptions(
                dest_dir=tmp_path / "out",
                max_file_size=5,
                max_total_size=100,
            ),
        )


def test_service_caps_archive_path_length(tmp_path: Path) -> None:
    archive_path = _make_zip(tmp_path / "path.zip", "folder/long-name.txt", b"ok")
    service = ArchiveService(safety_limits=SafetyLimits(max_path_length=10))

    with pytest.raises(UnsafeArchiveError, match="長すぎ"):
        service.extract(
            archive_path,
            ExtractionOptions(dest_dir=tmp_path / "out", max_path_length=260),
        )


def test_service_limit_does_not_mutate_original_options(tmp_path: Path) -> None:
    archive_path = _make_zip(tmp_path / "normal.zip", "small.txt", b"ok")
    options = ExtractionOptions(
        dest_dir=tmp_path / "out",
        max_file_size=50,
        max_total_size=100,
        max_path_length=100,
    )
    service = ArchiveService(
        safety_limits=SafetyLimits(
            max_single_file_size=10,
            max_total_size=20,
            max_path_length=50,
        )
    )

    service.extract(archive_path, options)

    assert options.max_file_size == 50
    assert options.max_total_size == 100
    assert options.max_path_length == 100
    assert (tmp_path / "out" / "small.txt").read_bytes() == b"ok"


def test_service_preview_limit_reaches_backend_read_entry(tmp_path: Path) -> None:
    archive_path = _make_zip(tmp_path / "preview.zip", "hello.txt", b"Hello World")

    service = ArchiveService(safety_limits=SafetyLimits(preview_max_size=4))

    assert service.read_entry(archive_path, "hello.txt") is None

    default_service = ArchiveService()
    assert default_service.read_entry(archive_path, "hello.txt") == b"Hello World"


def test_extraction_defaults_match_safety_limits() -> None:
    """ExtractionOptions と SafetyLimits の既定値が一致することを保証する。

    ExtractionOptions の上限既定値は SafetyLimits から default_factory で導出される
    （models.py にリテラルの二重定義はない）。ここでは導出結果の値が対応関係
    （SafetyLimits.max_single_file_size ↔ ExtractionOptions.max_file_size など）を
    満たしていることを値で確認する。"""
    limits = SafetyLimits()
    options = ExtractionOptions(dest_dir=Path("."))

    assert options.max_total_size == limits.max_total_size
    assert options.max_file_size == limits.max_single_file_size
    assert options.max_entries == limits.max_entries
    assert options.max_compression_ratio == limits.max_compression_ratio
    assert options.max_path_length == limits.max_path_length


def test_default_limits_do_not_tighten_default_options() -> None:
    """既定の SafetyLimits による min マージが既定 ExtractionOptions を変えないこと。"""
    service = ArchiveService()
    options = ExtractionOptions(dest_dir=Path("."))

    effective = service._effective_extraction_options(options)

    assert effective.max_total_size == options.max_total_size
    assert effective.max_file_size == options.max_file_size
    assert effective.max_entries == options.max_entries
    assert effective.max_compression_ratio == options.max_compression_ratio
    assert effective.max_path_length == options.max_path_length
