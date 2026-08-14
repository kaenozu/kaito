"""
src/kaito/archive/service.py
アーカイブ操作のサービス層 (GUIとバックエンドの橋渡し)
関連: archive/zip_backend.py, archive/sevenzip_backend.py, gui/unzip_app.py
"""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path
from typing import Optional

from kaito.archive.inspection import (
    ArchiveSafetyReport,
    IntegrityCheckResult,
    inspect_archive,
)
from kaito.archive.safety import ensure_no_reparse_ancestors
from kaito.archive.sevenzip_backend import SevenZipBackend
from kaito.archive.zip_backend import ZipBackend
from kaito.domain.errors import (
    CompressionFailedError,
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
    """GUIと形式別バックエンドを分離するアーカイブ操作サービス。"""

    SUPPORTED_EXTENSIONS = frozenset({".zip", ".rar", ".7z"})

    def __init__(
        self,
        safety_limits: Optional[SafetyLimits] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> None:
        self._cancel_event = cancel_event or threading.Event()
        self._safety_limits = safety_limits or SafetyLimits()
        self._zip_backend = ZipBackend(
            cancel_event=self._cancel_event,
            preview_max_size=self._safety_limits.preview_max_size,
        )
        self._sevenzip_backend = SevenZipBackend(
            cancel_event=self._cancel_event,
            preview_max_size=self._safety_limits.preview_max_size,
        )

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

    def _encrypted_zip_uses_sevenzip(self, path: str | Path) -> bool:
        """暗号化ZIPはAESを含めて同梱7-Zipで処理する。"""
        return self._zip_backend.list_archive(Path(path)).is_encrypted

    def _effective_extraction_options(
        self, options: ExtractionOptions
    ) -> ExtractionOptions:
        """サービス全体の上限を超えない展開オプションを返す。"""
        limits = self._safety_limits
        return replace(
            options,
            max_total_size=min(options.max_total_size, limits.max_total_size),
            max_file_size=min(options.max_file_size, limits.max_single_file_size),
            max_entries=min(options.max_entries, limits.max_entries),
            max_compression_ratio=min(
                options.max_compression_ratio, limits.max_compression_ratio
            ),
            max_path_length=min(options.max_path_length, limits.max_path_length),
        )

    def list_archive(
        self, path: str | Path, password: Optional[str] = None
    ) -> ArchiveInfo:
        backend = self._get_backend(path)
        if isinstance(backend, SevenZipBackend):
            self._raise_if_backend_unavailable(backend, path)
        return backend.list_archive(Path(path), password=password)

    def analyze_archive(self, info: ArchiveInfo) -> ArchiveSafetyReport:
        """一覧情報だけを使って非破壊の安全診断を行う。"""
        return inspect_archive(info, self._safety_limits)

    def test_archive(
        self, path: str | Path, password: Optional[str] = None
    ) -> IntegrityCheckResult:
        """展開せずに全データのCRC/整合性を検査する。"""
        archive_path = Path(path)
        if archive_path.suffix.lower() == ".zip" and self._encrypted_zip_uses_sevenzip(
            archive_path
        ):
            self._raise_if_backend_unavailable(self._sevenzip_backend, archive_path)
            return self._sevenzip_backend.test_archive(archive_path, password=password)

        backend = self._get_backend(archive_path)
        if isinstance(backend, SevenZipBackend):
            self._raise_if_backend_unavailable(backend, archive_path)
        return backend.test_archive(archive_path, password=password)

    def backend_info(self) -> dict[str, object]:
        """診断レポート用に7-Zipバックエンド情報を返す。"""
        return self._sevenzip_backend.backend_info()

    def extract(self, path: str | Path, options: ExtractionOptions) -> None:
        archive_path = Path(path)
        effective_options = self._effective_extraction_options(options)
        if archive_path.suffix.lower() == ".zip" and self._encrypted_zip_uses_sevenzip(
            archive_path
        ):
            self._raise_if_backend_unavailable(self._sevenzip_backend, archive_path)
            self._sevenzip_backend.extract(archive_path, effective_options)
            return

        backend = self._get_backend(archive_path)
        if isinstance(backend, SevenZipBackend):
            self._raise_if_backend_unavailable(backend, archive_path)
        backend.extract(archive_path, effective_options)

    def create(self, options: CompressionOptions) -> None:
        if options.output_path.exists():
            raise CompressionFailedError(
                "出力先ファイルが既に存在します",
                archive_path=str(options.output_path),
            )

        collisions = self.find_duplicate_names(options.sources)
        if collisions:
            names = ", ".join(name for name, _ in collisions[:5])
            suffix = " ..." if len(collisions) > 5 else ""
            raise CompressionFailedError(
                f"アーカイブ内の名前が重複します: {names}{suffix}",
                archive_path=str(options.output_path),
            )

        extension = options.output_path.suffix.lower()
        if extension == ".zip":
            if options.password:
                self._raise_if_backend_unavailable(
                    self._sevenzip_backend, options.output_path
                )
                self._sevenzip_backend.create(options)
            else:
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
            if self._encrypted_zip_uses_sevenzip(archive_path):
                self._raise_if_backend_unavailable(self._sevenzip_backend, archive_path)
                return self._sevenzip_backend.read_entry(
                    archive_path, entry_name, password=password
                )
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
        dest: Path,
        archive_path: Path,
        entries: list[ArchiveEntry],
        *,
        avoid_existing: bool = False,
    ) -> Path:
        """アーカイブ構成に応じて安全な展開先を決定する。"""
        roots: set[str] = set()
        has_root_file = False
        for entry in entries:
            if "/" in entry.name:
                roots.add(entry.name.split("/", 1)[0])
            elif entry.name:
                has_root_file = True

        needs_container = len(roots) != 1 or has_root_file
        resolved = dest / archive_path.stem if needs_container else dest
        if avoid_existing and needs_container and resolved.exists():
            base_name = resolved.name
            for index in range(2, 10_000):
                candidate = resolved.with_name(f"{base_name} ({index})")
                if not candidate.exists():
                    resolved = candidate
                    break
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
    def _planned_entry_paths(source: Path) -> list[tuple[str, Path]]:
        """現在のバックエンドが作るアーカイブ内パスを列挙する。"""
        if not source.is_dir():
            return [(source.name, source)]

        planned: list[tuple[str, Path]] = []
        for item in source.rglob("*"):
            archive_name = item.relative_to(source.parent).as_posix()
            if item.is_dir():
                archive_name = archive_name.rstrip("/") + "/"
            planned.append((archive_name, item))
        return planned

    @classmethod
    def find_duplicate_names(cls, sources: list[Path]) -> list[tuple[str, list[Path]]]:
        """Windowsへの展開時に同じ名前となるエントリを検出する。"""
        by_normalized_name: dict[str, tuple[str, list[Path]]] = {}
        for source in sources:
            for archive_name, origin in cls._planned_entry_paths(source):
                normalized = archive_name.replace("\\", "/").rstrip("/").casefold()
                if not normalized:
                    continue
                if normalized not in by_normalized_name:
                    by_normalized_name[normalized] = (archive_name, [origin])
                else:
                    by_normalized_name[normalized][1].append(origin)

        return [
            (archive_name, paths)
            for archive_name, paths in by_normalized_name.values()
            if len(paths) > 1
        ]
