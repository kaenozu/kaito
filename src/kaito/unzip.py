"""
src/kaito/unzip.py
ZIP/RAR/7zファイルの解凍・圧縮コアロジック (新アーキテクチャへの委譲)
ZIP: zipfile 標準ライブラリ
RAR/7z: 7-Zip CLI (7z.exe)
関連: archive/service.py, archive/zip_backend.py, archive/sevenzip_backend.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from kaito.archive.service import ArchiveService
from kaito.domain.models import (
    ArchiveEntry,
    ExtractionOptions,
    SafetyLimits,
)

# 単一インスタンス (遅延初期化)
_service: Optional[ArchiveService] = None


def _get_service() -> ArchiveService:
    global _service
    if _service is None:
        _service = ArchiveService()
    return _service


# 外部公開型
ZipEntry = ArchiveEntry
ProgressCallback = Callable[[int, int, str], None]

ARCHIVE_EXTENSIONS = frozenset({".zip", ".rar", ".7z"})

# ZIPファイル名のエンコーディング解決
_ZIP_ENCODINGS: tuple[str, ...] = ()
_FALLBACK_ENCODINGS = ["utf-8", "cp932", "gbk", "cp949", "shift_jis", "euc-kr"]


def get_zip_encodings() -> tuple[str, ...]:
    """ZIPファイル名のデコードに試すエンコーディング一覧"""
    global _ZIP_ENCODINGS
    if not _ZIP_ENCODINGS:
        import locale

        seen: set[str] = set()
        encodings: list[str] = []
        for enc in _FALLBACK_ENCODINGS:
            if enc not in seen:
                seen.add(enc)
                encodings.append(enc)
        try:
            sys_enc = locale.getencoding()
            sys_lower = sys_enc.lower()
            if sys_lower not in (e.lower() for e in seen):
                encodings.append(sys_enc)
        except Exception:
            pass
        _ZIP_ENCODINGS = tuple(encodings)
    return _ZIP_ENCODINGS


def is_supported(path: str | Path) -> bool:
    """対応アーカイブ形式かを判定"""
    return _get_service().is_supported(path)


def list_archive(
    path: str | Path, _password: Optional[str] = None
) -> tuple[list[ArchiveEntry], bool]:
    """アーカイブの内容一覧を返す

    Returns:
        (entries, is_encrypted)
    """
    info = _get_service().list_archive(path, password=_password)
    return info.entries, info.is_encrypted


def list_entries(zip_path: str | Path) -> tuple[list[ArchiveEntry], bool]:
    """ZIPファイルの内容一覧 (list_archiveのエイリアス)"""
    return list_archive(zip_path)


def extract_archive(
    path: str | Path,
    dest: str | Path,
    password: Optional[str] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> None:
    """アーカイブを展開する"""

    def cb(current: int, total: int, name: str) -> None:
        if on_progress:
            on_progress(current, total, name)

    # 展開先の SafetyLimits を適用
    limits = SafetyLimits()
    options = ExtractionOptions(
        dest_dir=Path(dest),
        password=password,
        on_progress=cb,
        max_total_size=limits.max_total_size,
        max_file_size=limits.max_single_file_size,
        max_entries=limits.max_entries,
        max_compression_ratio=limits.max_compression_ratio,
    )
    _get_service().extract(path, options)


def extract(
    zip_path: str | Path,
    dest: str | Path,
    password: Optional[str] = None,
    on_progress: Optional[ProgressCallback] = None,
    members: Optional[list[str]] = None,
) -> None:
    """ZIPファイルを展開 (メンバー指定対応)"""
    limits = SafetyLimits()
    options = ExtractionOptions(
        dest_dir=Path(dest),
        password=password,
        members=members,
        on_progress=on_progress,
        max_total_size=limits.max_total_size,
        max_file_size=limits.max_single_file_size,
        max_entries=limits.max_entries,
        max_compression_ratio=limits.max_compression_ratio,
    )
    _get_service().extract(zip_path, options)


def extract_all(
    zip_path: str | Path,
    dest: str | Path,
    password: Optional[str] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> None:
    """全エントリを展開"""
    extract(zip_path, dest, password=password, on_progress=on_progress, members=None)


def create_archive(
    sources: list[Path],
    output: Path,
    on_progress: Optional[ProgressCallback] = None,
    compression_level: int = 1,
) -> None:
    """アーカイブを作成する"""
    from kaito.domain.models import CompressionOptions

    options = CompressionOptions(
        sources=sources,
        output_path=output,
        compression_level=compression_level,
        on_progress=on_progress,
    )
    _get_service().create(options)


def _validate_zip_member(name: str, dest: Path) -> Path:
    """ZIPエントリ名のパストラバーサルチェック (ArchiveServiceに委譲)"""
    from kaito.domain.models import validate_entry_path

    return validate_entry_path(name, dest)
