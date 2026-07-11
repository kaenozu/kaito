"""
src/kaito/domain/models.py
アーカイブ操作のドメインモデル
関連: archive/service.py, archive/zip_backend.py, archive/sevenzip_backend.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
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

    @property
    def is_file(self) -> bool:
        return not self.is_dir


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


def validate_entry_path(name: str, dest_dir: Path) -> Path:
    """アーカイブエントリ名のパストラバーサルをチェックし、安全な出力先パスを返す

    拒否対象:
    - 絶対パス (/ や \\\\ で始まる)
    - Windowsドライブパス (C:\\ 等)
    - UNCパス (\\\\server\\share)
    - 親ディレクトリ参照 (..)
    - 空パス
    - 正規化後に展開先外へ出るパス
    - Windows予約デバイス名 (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
    """
    if not name:
        raise UnsafeArchiveError("空のエントリ名は許可されません")

    # Windows ドライブパス (C:\ など) を拒否
    if len(name) >= 2 and name[1] == ":":
        raise UnsafeArchiveError(f"Windowsドライブパスは許可されません: {name}")

    # 絶対パス (/ や \ で始まる) を拒否
    if name.startswith("/") or name.startswith("\\"):
        raise UnsafeArchiveError(f"絶対パスは許可されません: {name}")

    # UNCパス (\\server\share) を拒否
    if name.startswith("\\\\"):
        raise UnsafeArchiveError(f"UNCパスは許可されません: {name}")

    # parent directory traversal (..) を拒否
    # 正規化して各パーツをチェック
    normalized = Path(name).as_posix()
    for part in normalized.split("/"):
        if part == "..":
            raise UnsafeArchiveError(
                f"親ディレクトリ参照を含むパスは許可されません: {name}"
            )
        # 代替データストリーム (ADS) チェック
        if ":" in part:
            raise UnsafeArchiveError(
                f"代替データストリームを含むパスは許可されません: {name}"
            )
        # Windows予約デバイス名チェック (拡張子除去後)
        base_part = part.split(".")[0].upper() if part else ""
        if base_part in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            "COM1",
            "COM2",
            "COM3",
            "COM4",
            "COM5",
            "COM6",
            "COM7",
            "COM8",
            "COM9",
            "LPT1",
            "LPT2",
            "LPT3",
            "LPT4",
            "LPT5",
            "LPT6",
            "LPT7",
            "LPT8",
            "LPT9",
        }:
            raise UnsafeArchiveError(f"Windows予約デバイス名は許可されません: {name}")

    # シンボリックリンクエントリを拒否
    # (7zの-slt出力で確認、リンクは後続のresolveで保護される)

    # 展開先を解決して安全確認
    target = (dest_dir / name).resolve()
    dest_resolved = dest_dir.resolve()
    if not str(target).startswith(str(dest_resolved)):
        raise UnsafeArchiveError(f"安全でないパスが含まれています: {name}")

    return target


def check_archive_safety(
    entries: list[ArchiveEntry], options: ExtractionOptions
) -> None:
    """アーカイブ全体の安全性を評価 (アーカイブ爆弾対策)

    チェック項目:
    - エントリ数上限
    - 単一ファイルサイズ上限
    - 合計展開サイズ上限
    - 圧縮率 (圧縮後サイズ > 0 の場合)
    """
    if len(entries) > options.max_entries:
        raise ArchiveBombError(
            f"エントリ数が上限を超えています ({len(entries)} > {options.max_entries})",
            limit_name="max_entries",
            limit_value=options.max_entries,
            actual_value=len(entries),
        )

    total_size = 0
    for entry in entries:
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

    # 圧縮率チェック (圧縮後サイズが取得できている場合)
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
