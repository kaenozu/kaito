"""アーカイブ展開の共通安全処理。"""

from __future__ import annotations

import shutil
from pathlib import Path

from kaito.domain.errors import ArchiveBombError, ExtractionFailedError, UnsafeArchiveError
from kaito.domain.models import (
    ExtractionOptions,
    SafetyLimits,
    check_archive_safety,
    is_reparse_or_link,
    validate_entry_path,
)


def ensure_no_reparse_ancestors(path: Path) -> None:
    """既存の親要素にsymlink/junction/reparse pointがないことを確認する。"""
    candidate = path
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    for existing in (candidate, *candidate.parents):
        if is_reparse_or_link(existing):
            raise UnsafeArchiveError(
                f"展開先の親ディレクトリにリンクまたはreparse pointがあります: {existing}"
            )


def validate_staging_tree(staging: Path, options: ExtractionOptions) -> None:
    """外部展開後のツリーをファイルシステム上でも再検査する。"""
    count = 0
    total = 0
    for item in staging.rglob("*"):
        relative = item.relative_to(staging).as_posix()
        validate_entry_path(relative, staging)
        if is_reparse_or_link(item):
            raise UnsafeArchiveError(f"リンクが展開されました: {relative}")
        count += 1
        if count > options.max_entries:
            raise ArchiveBombError(
                "展開後のエントリ数が上限を超えました",
                limit_name="max_entries",
                limit_value=options.max_entries,
                actual_value=count,
            )
        if item.is_file():
            size = item.stat().st_size
            if size > options.max_file_size:
                raise ArchiveBombError(
                    f"展開後のファイルサイズが上限を超えました: {relative}",
                    limit_name="max_file_size",
                    limit_value=options.max_file_size,
                    actual_value=size,
                )
            total += size
            if total > options.max_total_size:
                raise ArchiveBombError(
                    "展開後の合計サイズが上限を超えました",
                    limit_name="max_total_size",
                    limit_value=options.max_total_size,
                    actual_value=total,
                )


def merge_staging_tree(staging: Path, destination: Path) -> None:
    """検査済みステージングツリーを既存ファイルを壊さず移動する。"""
    ensure_no_reparse_ancestors(destination)
    destination.mkdir(parents=True, exist_ok=True)

    directories = sorted(
        (item for item in staging.rglob("*") if item.is_dir()),
        key=lambda item: len(item.parts),
    )
    files = sorted(item for item in staging.rglob("*") if item.is_file())

    for directory in directories:
        relative = directory.relative_to(staging).as_posix()
        target = validate_entry_path(relative, destination)
        ensure_no_reparse_ancestors(target.parent)
        if target.exists() and not target.is_dir():
            raise ExtractionFailedError(f"展開先に同名ファイルがあります: {relative}")
        target.mkdir(parents=True, exist_ok=True)

    for source in files:
        relative = source.relative_to(staging).as_posix()
        target = validate_entry_path(relative, destination)
        ensure_no_reparse_ancestors(target.parent)
        if target.exists():
            raise ExtractionFailedError(f"展開先に同名項目があります: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))


__all__ = [
    "SafetyLimits",
    "check_archive_safety",
    "ensure_no_reparse_ancestors",
    "merge_staging_tree",
    "validate_entry_path",
    "validate_staging_tree",
]
