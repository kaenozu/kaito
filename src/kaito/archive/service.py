"""
src/kaito/archive/service.py
アーカイブ操作のサービス層 (GUIとバックエンドの橋渡し)
関連: archive/zip_backend.py, archive/sevenzip_backend.py, gui/unzip_app.py
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from kaito.archive.sevenzip_backend import SevenZipBackend
from kaito.archive.zip_backend import ZipBackend
from kaito.domain.errors import (
    ExternalToolNotFoundError,
    UnsupportedFormatError,
)
from kaito.domain.models import (
    ArchiveEntry,
    ArchiveInfo,
    CompressionOptions,
    ExtractionOptions,
    SafetyLimits,
)


class ArchiveService:
    """アーカイブ操作サービス

    GUIはこのサービスのみを呼び出し、バックエンドの種類を意識しない。
    スレッドセーフ: 各メソッドは独立して呼び出し可能。
    """

    # 対応拡張子 (小文字、ドット含む)
    SUPPORTED_EXTENSIONS = frozenset({".zip", ".rar", ".7z"})

    def __init__(
        self,
        safety_limits: Optional[SafetyLimits] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> None:
        self._cancel_event = cancel_event or threading.Event()
        self._zip_backend = ZipBackend()
        self._sevenzip_backend = SevenZipBackend(cancel_event=self._cancel_event)
        self._safety_limits = safety_limits or SafetyLimits()

    @property
    def safety_limits(self) -> SafetyLimits:
        return self._safety_limits

    def cancel(self) -> None:
        """Cancel current operation."""
        self._cancel_event.set()

    def reset_cancel(self) -> None:
        """Reset cancel flag for next operation."""
        self._cancel_event.clear()

    def is_supported(self, path: str | Path) -> bool:
        """対応アーカイブ形式かを判定"""
        return Path(path).suffix.lower() in self.SUPPORTED_EXTENSIONS

    def is_creation_supported(self, path: str | Path) -> bool:
        """この形式の作成をサポートしているか"""
        ext = Path(path).suffix.lower()
        if ext == ".zip":
            return True
        if ext == ".7z":
            return self._sevenzip_backend.supports_creation(ext)
        return False

    def _get_backend(self, path: str | Path) -> ZipBackend | SevenZipBackend:
        """パスに対応するバックエンドを返す"""
        ext = Path(path).suffix.lower()
        if ext == ".zip":
            return self._zip_backend
        elif ext in {".rar", ".7z"}:
            return self._sevenzip_backend
        else:
            raise UnsupportedFormatError(ext)

    def list_archive(
        self, path: str | Path, password: Optional[str] = None
    ) -> ArchiveInfo:
        """アーカイブの内容一覧を取得"""
        backend = self._get_backend(path)

        # 7z/RARの可用性チェック
        if isinstance(backend, SevenZipBackend):
            available, error_msg = backend.check_tool_availability()
            if not available:
                raise ExternalToolNotFoundError(
                    "7z (7-Zip)", error_msg, archive_path=str(path)
                )

        return backend.list_archive(Path(path), password=password)

    def extract(self, path: str | Path, options: ExtractionOptions) -> None:
        """アーカイブを展開"""
        backend = self._get_backend(path)

        # 7z/RARの可用性チェック
        if isinstance(backend, SevenZipBackend):
            available, error_msg = backend.check_tool_availability()
            if not available:
                raise ExternalToolNotFoundError(
                    "7z (7-Zip)", error_msg, archive_path=str(path)
                )

        backend.extract(Path(path), options)

    def create(self, options: CompressionOptions) -> None:
        """アーカイブを作成"""
        ext = options.output_path.suffix.lower()
        if ext == ".zip":
            self._zip_backend.create(options)
        elif ext == ".7z":
            available, error_msg = self._sevenzip_backend.check_tool_availability()
            if not available:
                raise ExternalToolNotFoundError(
                    "7z (7-Zip)", error_msg, archive_path=str(options.output_path)
                )
            self._sevenzip_backend.create(options)
        elif ext == ".rar":
            raise UnsupportedFormatError(
                "RAR", "RAR形式の作成はライセンス上の制約によりサポートされていません"
            )
        else:
            raise UnsupportedFormatError(ext)

    def read_entry(
        self, path: str | Path, entry_name: str, password: Optional[str] = None
    ) -> Optional[bytes]:
        """アーカイブ内の1エントリを読み込む (プレビュー用)

        ZIPは zipfile で直接読み込み。
        RAR/7zは 7z CLI で一時展開して読み込み。
        """
        p = Path(path)
        ext = p.suffix.lower()
        if ext == ".zip":
            return self._zip_backend.read_entry(p, entry_name, password=password)
        elif ext in {".rar", ".7z"}:
            return self._sevenzip_backend.read_entry(p, entry_name, password=password)
        return None

    def check_sevenzip_available(self) -> tuple[bool, Optional[str]]:
        """7-Zip CLI が利用可能か確認"""
        return self._sevenzip_backend.check_tool_availability()

    @staticmethod
    def resolve_extract_dest(
        dest: Path, archive_path: Path, entries: list[ArchiveEntry]
    ) -> Path:
        """アーカイブ構成に応じて展開先を決定し、二重ネストを防ぐ

        全エントリが1つのトップレベルディレクトリを共有している場合、
        dest 直下に展開する。それ以外は dest/archive_stem/ を作成する。
        """
        roots: set[str] = set()
        has_root_file = False
        for e in entries:
            if "/" in e.name:
                root = e.name.split("/")[0]
                roots.add(root)
            elif e.name:
                has_root_file = True

        if len(roots) == 1 and not has_root_file:
            return dest
        return dest / archive_path.stem

    @staticmethod
    def check_self_contained(sources: list[Path], output_path: Path) -> Optional[str]:
        """出力ファイルが圧縮対象に含まれていないかチェック

        Returns:
            問題がある場合はエラーメッセージ、なければNone
        """
        output_resolved = output_path.resolve()
        for src in sources:
            src_resolved = src.resolve()
            if src_resolved == output_resolved:
                return "出力ファイル自身が圧縮対象に含まれています"
            if src_resolved.is_dir() and output_resolved.is_relative_to(src_resolved):
                return "出力先フォルダが圧縮対象に含まれています"
        return None

    @staticmethod
    def find_duplicate_names(sources: list[Path]) -> list[tuple[str, list[Path]]]:
        """圧縮対象内の重複ファイル名を検出"""
        name_map: dict[str, list[Path]] = {}
        for src in sources:
            if src.is_dir():
                for f in src.rglob("*"):
                    if f.is_file():
                        name_map.setdefault(f.name, []).append(f)
            else:
                name_map.setdefault(src.name, []).append(src)

        return [(name, paths) for name, paths in name_map.items() if len(paths) > 1]
