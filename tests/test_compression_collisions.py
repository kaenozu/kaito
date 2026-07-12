"""圧縮時のアーカイブ内パス衝突テスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from kaito.archive.service import ArchiveService
from kaito.domain.errors import CompressionFailedError
from kaito.domain.models import CompressionOptions


def test_same_file_name_from_different_directories_is_rejected(
    tmp_path: Path,
) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first = first_dir / "report.txt"
    second = second_dir / "report.txt"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    output = tmp_path / "collision.zip"

    with pytest.raises(CompressionFailedError, match="名前が重複"):
        ArchiveService().create(
            CompressionOptions(sources=[first, second], output_path=output)
        )

    assert not output.exists()


def test_case_only_file_name_collision_is_rejected(tmp_path: Path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first = first_dir / "Report.txt"
    second = second_dir / "report.TXT"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")

    collisions = ArchiveService.find_duplicate_names([first, second])

    assert len(collisions) == 1
    assert set(collisions[0][1]) == {first, second}


def test_same_basename_in_distinct_subdirectories_is_allowed(tmp_path: Path) -> None:
    source = tmp_path / "project"
    (source / "a").mkdir(parents=True)
    (source / "b").mkdir(parents=True)
    (source / "a" / "readme.txt").write_text("a", encoding="utf-8")
    (source / "b" / "readme.txt").write_text("b", encoding="utf-8")

    assert ArchiveService.find_duplicate_names([source]) == []


def test_same_root_directory_name_from_different_parents_is_rejected(
    tmp_path: Path,
) -> None:
    first = tmp_path / "one" / "project"
    second = tmp_path / "two" / "project"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "data.txt").write_text("first", encoding="utf-8")
    (second / "data.txt").write_text("second", encoding="utf-8")

    collisions = ArchiveService.find_duplicate_names([first, second])

    names = {name.rstrip("/").casefold() for name, _ in collisions}
    assert "project/data.txt" in names


@pytest.mark.parametrize("extension", [".zip", ".7z"])
def test_existing_output_is_not_overwritten(tmp_path: Path, extension: str) -> None:
    source = tmp_path / "source.txt"
    source.write_text("new data", encoding="utf-8")
    output = tmp_path / f"existing{extension}"
    output.write_bytes(b"original archive bytes")

    with pytest.raises(CompressionFailedError, match="既に存在"):
        ArchiveService().create(
            CompressionOptions(sources=[source], output_path=output)
        )

    assert output.read_bytes() == b"original archive bytes"
