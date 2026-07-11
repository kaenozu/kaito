"""
src/kaito/archive/service.py
アーカイブ操作のサービス層 (GUIとバックエンドの橋渡し)
関連: archive/zip_backend.py, archive/sevenzip_backend.py, gui/unzip_app.py
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from kaito.archive.safety import ensure_no_reparse_ancestors
from kaito.archive.sevenzip_backend import SevenZipBackend
from kaito.archive.zip_backend import ZipBackend
from kaito.domain.errors import ExternalToolNotFoundError, UnsupportedFormatError
from kaito.domain.models import (
    ArchiveEntry,
    ArchiveInfo,
    CompressionOptions,
    ExtractionOptions,
    SafetyLimits,
)


class ArchiveService:
    """GUIと形式別バックエンドを分離するアーカイブ操作サービス。"""

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
        """現在の操作へキャンセルを通知する。"""
        self._cancel_event.set()

    def reset_cancel(self) -> None:
        """次の操作に備えてキャンセル状態を解除する。"""
        self._cancel_event.clear()

    def is_cancelled(self) -> bool:
        """現在の操作にキャンセルが通知されているか返す。"""
        return self._cancel_event.is_set()

    def is_supported(self, path: str | Path) -> bool:
        return Path(path).suffix.lower() in self.SUPPORTED_EXTENSIONS

    def is_creation_supported(self, path: str | Path) -> bool:
        extension = Path(path).suffix.lower()
        if extension == ".zip":
            return True
        if extension == ".7z":
            return self._sevenzip_backend.supports_creation(extension)
        return False

    def _get_backend(self, path: str | Path) -> ZipBackend | SevenZipBackend:
        extension = Path(path).suffix.lower()
        if extension == ".zip":
            return self._zip_backend
        if extension in {".rar", ".7z"}:
            return self._sevenzip_backend
        raise UnsupportedFormatError(extension)

    @staticmethod
    def _raise_if_backend_unavailable(
        backend: SevenZipBackend, archive_path: str | Path
    ) -> None:
        available, error_message = backend.check_tool_availability()
        if not available:
            raise ExternalToolNotFoundError(
                "7z (7-Zip)", error_message, archive_path=str(archive_path)
            )

    def list_archive(
        self, path: str | Path, password: Optional[str] = None
    ) -> ArchiveInfo:
        backend = self._get_backend(path)
        if isinstance(backend, SevenZipBackend):
            self._raise_if_backend_unavailable(backend, path)
        return backend.list_archive(Path(path), password=password)

    def extract(self, path: str | Path, options: ExtractionOptions) -> None:
        backend = self._get_backend(path)
        if isinstance(backend, SevenZipBackend):
            self._raise_if_backend_unavailable(backend, path)
        backend.extract(Path(path), options)

    def create(self, options: CompressionOptions) -> None:
        extension = options.output_path.suffix.lower()
        if extension == ".zip":
            self._zip_backend.create(options)
            return
        if extension == ".7z":
            self._raise_if_backend_unavailable(
                self._sevenzip_backend, options.output_path
            )
            self._sevenzip_backend.create(options)
            return
        if extension == ".rar":
            raise UnsupportedFormatError(
                "RAR", "RAR形式の作成はライセンス上の制約によりサポートされていません"
            )
        raise UnsupportedFormatError(extension)

    def read_entry(
        self, path: str | Path, entry_name: str, password: Optional[str] = None
    ) -> Optional[bytes]:
        archive_path = Path(path)
        extension = archive_path.suffix.lower()
        if extension == ".zip":
            return self._zip_backend.read_entry(
                archive_path, entry_name, password=password
            )
        if extension in {".rar", ".7z"}:
            self._raise_if_backend_unavailable(self._sevenzip_backend, archive_path)
            return self._sevenzip_backend.read_entry(
                archive_path, entry_name, password=password
            )
        return None

    def check_sevenzip_available(self) -> tuple[bool, Optional[str]]:
        return self._sevenzip_backend.check_tool_availability()

    @staticmethod
    def resolve_extract_dest(
        dest: Path, archive_path: Path, entries: list[ArchiveEntry]
    ) -> Path:
        """アーカイブ構成に応じて安全な展開先を決定する。"""
        roots: set[str] = set()
        has_root_file = False
        for entry in entries:
            if "/" in entry.name:
                roots.add(entry.name.split("/", 1)[0])
            elif entry.name:
                has_root_file = True

        resolved = dest if len(roots) == 1 and not has_root_file else dest / archive_path.stem
        ensure_no_reparse_ancestors(resolved)
        return resolved

    @staticmethod
    def check_self_contained(sources: list[Path], output_path: Path) -> Optional[str]:
        output_resolved = output_path.resolve(strict=False)
        for source in sources:
            source_resolved = source.resolve(strict=False)
            if source_resolved == output_resolved:
                return "出力ファイル自身が圧縮対象に含まれています"
            if source_resolved.is_dir() and output_resolved.is_relative_to(
                source_resolved
            ):
                return "出力先フォルダが圧縮対象に含まれています"
        return None

    @staticmethod
    def find_duplicate_names(sources: list[Path]) -> list[tuple[str, list[Path]]]:
        name_map: dict[str, list[Path]] = {}
        for source in sources:
            if source.is_dir():
                for file_path in source.rglob("*"):
                    if file_path.is_file():
                        name_map.setdefault(file_path.name, []).append(file_path)
            else:
                name_map.setdefault(source.name, []).append(source)
        return [
            (name, paths) for name, paths in name_map.items() if len(paths) > 1
        ]
