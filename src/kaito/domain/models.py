"""
src/kaito/domain/models.py
アーカイブ操作のドメインモデル
関連: archive/service.py, archive/zip_backend.py, archive/sevenzip_backend.py
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable, Optional

from kaito.domain.errors import ArchiveBombError, UnsafeArchiveError


@dataclass(frozen=True)
class ArchiveEntry:
    """アーカイブ内の1エントリ"""

    name: str
    size: int
    compressed_size: int
    modified: datetime
    is_dir: bool
    is_encrypted: bool = False
    is_link: bool = False
    link_target: Optional[str] = None

    @property
    def is_file(self) -> bool:
        return not self.is_dir and not self.is_link


@dataclass(frozen=True)
class ArchiveInfo:
    """アーカイブの基本情報"""

    path: Path
    entries: list[ArchiveEntry]
    is_encrypted: bool
    format_name: str  # "zip", "7z", "rar"

    @property
    def total_size(self) -> int:
        return sum(e.size for e in self.entries)

    @property
    def total_compressed_size(self) -> int:
        return sum(e.compressed_size for e in self.entries)

    @property
    def file_count(self) -> int:
        return sum(1 for e in self.entries if e.is_file)

    @property
    def dir_count(self) -> int:
        return sum(1 for e in self.entries if e.is_dir)


ProgressCallback = Callable[[int, int, str], None]
"""進捗コールバック: (current, total, current_name)"""


@dataclass
class SafetyLimits:
    """安全性制限の設定"""

    max_total_size: int = 10 * 1024 * 1024 * 1024  # 10GB
    max_single_file_size: int = 2 * 1024 * 1024 * 1024  # 2GB
    max_entries: int = 100000
    max_compression_ratio: float = 1000.0
    max_path_length: int = 260
    preview_max_size: int = 10 * 1024 * 1024  # 10MB
    preview_max_image_pixels: int = 4000 * 3000  # 12MP
    extraction_timeout_seconds: float = 300.0


@dataclass
class ExtractionOptions:
    """展開オプション"""

    dest_dir: Path
    password: Optional[str] = None
    members: Optional[list[str]] = None  # None = 全展開
    on_progress: Optional[ProgressCallback] = None
    # 安全性チェック用
    max_total_size: int = 10 * 1024 * 1024 * 1024  # 10GB
    max_file_size: int = 2 * 1024 * 1024 * 1024  # 2GB
    max_entries: int = 100000
    max_compression_ratio: float = 1000.0


@dataclass
class CompressionOptions:
    """圧縮オプション"""

    sources: list[Path]
    output_path: Path
    compression_level: int = 1  # 0=無圧縮, 1=最速, 9=最高圧縮
    password: Optional[str] = None
    on_progress: Optional[ProgressCallback] = None


class ArchiveBackend:
    """アーカイブバックエンドのプロトコル (インターフェース)"""

    def list_archive(self, path: Path, password: Optional[str] = None) -> ArchiveInfo:
        """アーカイブ内容を取得"""
        raise NotImplementedError

    def extract(self, path: Path, options: ExtractionOptions) -> None:
        """アーカイブを展開"""
        raise NotImplementedError

    def create(self, options: CompressionOptions) -> None:
        """アーカイブを作成 (ZIP, 7zのみ対応)"""
        raise NotImplementedError

    def check_tool_availability(self) -> tuple[bool, Optional[str]]:
        """必要な外部ツールが利用可能か確認
        Returns: (available, tool_name_if_unavailable)
        """
        raise NotImplementedError

    def supports_format(self, extension: str) -> bool:
        """このバックエンドが対応する拡張子か"""
        raise NotImplementedError

    def supports_creation(self, extension: str) -> bool:
        """この拡張子の作成をサポートしているか"""
        raise NotImplementedError


_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _normalized_archive_parts(name: str) -> tuple[str, ...]:
    """アーカイブ内部パスをOS非依存の相対パス部品へ正規化する。"""
    if not name or "\x00" in name:
        raise UnsafeArchiveError("空またはNULを含むエントリ名は許可されません")

    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("//"):
        raise UnsafeArchiveError(f"絶対パスまたはUNCパスは許可されません: {name}")
    if len(normalized) >= 2 and normalized[1] == ":":
        raise UnsafeArchiveError(f"Windowsドライブパスは許可されません: {name}")

    pure = PurePosixPath(normalized)
    parts: list[str] = []
    for part in pure.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            raise UnsafeArchiveError(
                f"親ディレクトリ参照を含むパスは許可されません: {name}"
            )
        if ":" in part:
            raise UnsafeArchiveError(
                f"代替データストリームを含むパスは許可されません: {name}"
            )
        # Windowsでは末尾の空白・ピリオドが正規化され、別名衝突の原因になる。
        if part != part.rstrip(" ."):
            raise UnsafeArchiveError(
                f"末尾に空白またはピリオドを含む名前は許可されません: {name}"
            )
        base_part = part.split(".", 1)[0].upper()
        if base_part in _WINDOWS_RESERVED_NAMES:
            raise UnsafeArchiveError(f"Windows予約デバイス名は許可されません: {name}")
        parts.append(part)

    if not parts:
        raise UnsafeArchiveError("有効なパス要素を含まないエントリ名です")
    return tuple(parts)


def validate_entry_path(name: str, dest_dir: Path) -> Path:
    """安全なアーカイブ内部パスだけを展開先配下へ解決する。"""
    parts = _normalized_archive_parts(name)
    dest_resolved = dest_dir.resolve(strict=False)
    target = dest_resolved.joinpath(*parts).resolve(strict=False)
    try:
        target.relative_to(dest_resolved)
    except ValueError as exc:
        raise UnsafeArchiveError(f"安全でないパスが含まれています: {name}") from exc
    return target


def is_reparse_or_link(path: Path) -> bool:
    """既存パスがシンボリックリンクまたはWindows reparse pointか判定する。"""
    if path.is_symlink():
        return True
    try:
        attrs = path.lstat().st_file_attributes  # type: ignore[attr-defined]
    except (AttributeError, FileNotFoundError, OSError):
        return False
    reparse_flag = getattr(os.stat_result, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attrs & reparse_flag)


def check_archive_safety(
    entries: list[ArchiveEntry], options: ExtractionOptions
) -> None:
    """アーカイブ全体の安全性を評価する。"""
    if len(entries) > options.max_entries:
        raise ArchiveBombError(
            f"エントリ数が上限を超えています ({len(entries)} > {options.max_entries})",
            limit_name="max_entries",
            limit_value=options.max_entries,
            actual_value=len(entries),
        )

    total_size = 0
    for entry in entries:
        validate_entry_path(entry.name, options.dest_dir)
        if entry.is_link:
            target = f" -> {entry.link_target}" if entry.link_target else ""
            raise UnsafeArchiveError(
                f"リンクエントリは展開できません: {entry.name}{target}"
            )
        if entry.size < 0 or entry.compressed_size < 0:
            raise UnsafeArchiveError(f"不正なサイズ情報です: {entry.name}")
        if entry.size > options.max_file_size:
            raise ArchiveBombError(
                f"単一ファイルサイズが上限を超えています: {entry.name} ({entry.size} > {options.max_file_size})",
                limit_name="max_file_size",
                limit_value=options.max_file_size,
                actual_value=entry.size,
            )
        total_size += entry.size

    if total_size > options.max_total_size:
        raise ArchiveBombError(
            f"合計展開サイズが上限を超えています ({total_size} > {options.max_total_size})",
            limit_name="max_total_size",
            limit_value=options.max_total_size,
            actual_value=total_size,
        )

    total_compressed = sum(e.compressed_size for e in entries if e.compressed_size > 0)
    if total_compressed > 0:
        ratio = total_size / total_compressed
        if ratio > options.max_compression_ratio:
            raise ArchiveBombError(
                f"圧縮率が異常です (ratio={ratio:.1f} > {options.max_compression_ratio})",
                limit_name="max_compression_ratio",
                limit_value=int(options.max_compression_ratio),
                actual_value=int(ratio),
            )
