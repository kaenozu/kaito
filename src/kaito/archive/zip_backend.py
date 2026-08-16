"""ZIP作成専用バックエンド (標準ライブラリ zipfile)。

読み取り系 (一覧・展開・プレビュー・整合性検査) は DllArchiveBackend
(同梱 7z.dll / IInArchive) に一本化されたため、このバックエンドは
パスワードなし ZIP の作成のみを担う。暗号化 ZIP の作成は
SevenZipBackend (7z.exe CLI) が担う。
"""

from __future__ import annotations

import os
import tempfile
import threading
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Optional

from kaito.domain.errors import (
    CancelledError,
    CompressionFailedError,
)
from kaito.domain.models import (
    CompressionOptions,
    is_reparse_or_link,
)


class ZipBackend:
    """標準ライブラリzipfileを使用するZIP作成バックエンド。"""

    name = "zip"
    supported_extensions = frozenset({".zip"})
    can_create = True

    _IO_CHUNK_SIZE = 1024 * 1024

    def __init__(self, cancel_event: Optional[threading.Event] = None) -> None:
        self._cancel_event = cancel_event or threading.Event()

    def _check_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise CancelledError()

    def _iter_source_items(self, source: Path) -> Iterator[Path]:
        """Yield a directory tree without ever descending through a link/reparse point."""
        self._check_cancelled()
        if is_reparse_or_link(source):
            raise CompressionFailedError(
                f"リンクまたはreparse pointは圧縮できません: {source}"
            )
        if not source.is_dir():
            return

        stack = [source]
        while stack:
            directory = stack.pop()
            try:
                children = sorted(
                    directory.iterdir(),
                    key=lambda item: item.name.casefold(),
                    reverse=True,
                )
            except OSError as exc:
                raise CompressionFailedError(
                    f"圧縮対象を列挙できません: {directory}: {exc}"
                ) from exc
            for item in children:
                self._check_cancelled()
                if is_reparse_or_link(item):
                    raise CompressionFailedError(
                        f"リンクまたはreparse pointは圧縮できません: {item}"
                    )
                yield item
                if item.is_dir():
                    stack.append(item)

    def _count_files(self, sources: list[Path]) -> int:
        total = 0
        for source in sources:
            self._check_cancelled()
            if source.is_dir():
                total += sum(
                    1 for item in self._iter_source_items(source) if item.is_file()
                )
            else:
                if is_reparse_or_link(source):
                    raise CompressionFailedError(
                        f"リンクまたはreparse pointは圧縮できません: {source}"
                    )
                total += 1
        return total

    def _write_file(
        self,
        archive: zipfile.ZipFile,
        source: Path,
        archive_name: str,
        compression_level: int,
    ) -> None:
        self._check_cancelled()
        info = zipfile.ZipInfo.from_file(source, arcname=archive_name)
        info.compress_type = zipfile.ZIP_DEFLATED
        setattr(info, "_compresslevel", compression_level)
        with (
            source.open("rb") as input_stream,
            archive.open(info, "w") as output_stream,
        ):
            while chunk := input_stream.read(self._IO_CHUNK_SIZE):
                self._check_cancelled()
                output_stream.write(chunk)
        self._check_cancelled()

    @staticmethod
    def _write_directory(
        archive: zipfile.ZipFile, source: Path, archive_name: str
    ) -> None:
        name = archive_name.rstrip("/") + "/"
        info = zipfile.ZipInfo.from_file(source, arcname=name)
        archive.writestr(info, b"")

    def _verify_archive(self, path: Path) -> None:
        with zipfile.ZipFile(path, "r") as verification:
            for info in verification.infolist():
                self._check_cancelled()
                if info.is_dir():
                    continue
                with verification.open(info, "r") as source:
                    while source.read(self._IO_CHUNK_SIZE):
                        self._check_cancelled()

    def create(self, options: CompressionOptions) -> None:
        self._check_cancelled()
        output_resolved = options.output_path.resolve(strict=False)
        for source in options.sources:
            self._check_cancelled()
            source_resolved = source.resolve(strict=False)
            if source_resolved == output_resolved or (
                source_resolved.is_dir()
                and output_resolved.is_relative_to(source_resolved)
            ):
                raise CompressionFailedError(
                    "出力アーカイブが圧縮対象に含まれています",
                    archive_path=str(options.output_path),
                )

        if not 0 <= options.compression_level <= 9:
            raise CompressionFailedError("圧縮レベルは0〜9で指定してください")
        if options.password:
            raise CompressionFailedError(
                "標準ZIPバックエンドは暗号化ZIPの作成に対応していません",
                archive_path=str(options.output_path),
            )

        total_files = self._count_files(options.sources)
        options.output_path.parent.mkdir(parents=True, exist_ok=True)

        temporary_path: Optional[Path] = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{options.output_path.stem}.",
                suffix=".tmp.zip",
                dir=options.output_path.parent,
            )
            os.close(descriptor)
            temporary_path = Path(temporary_name)
            done = 0
            with zipfile.ZipFile(
                temporary_path,
                "w",
                zipfile.ZIP_DEFLATED,
                compresslevel=options.compression_level,
            ) as archive:
                for source in options.sources:
                    self._check_cancelled()
                    if is_reparse_or_link(source):
                        raise CompressionFailedError(
                            f"リンクまたはreparse pointは圧縮できません: {source}"
                        )
                    if source.is_dir():
                        self._write_directory(archive, source, source.name)
                        for item in self._iter_source_items(source):
                            archive_name = item.relative_to(source.parent).as_posix()
                            if item.is_file():
                                self._write_file(
                                    archive,
                                    item,
                                    archive_name,
                                    options.compression_level,
                                )
                                done += 1
                                if options.on_progress:
                                    options.on_progress(done, total_files, item.name)
                                self._check_cancelled()
                            elif item.is_dir():
                                self._write_directory(archive, item, archive_name)
                    else:
                        self._write_file(
                            archive,
                            source,
                            source.name,
                            options.compression_level,
                        )
                        done += 1
                        if options.on_progress:
                            options.on_progress(done, total_files, source.name)
                        self._check_cancelled()

            self._check_cancelled()
            self._verify_archive(temporary_path)
            self._check_cancelled()
            os.replace(temporary_path, options.output_path)
            temporary_path = None
        except CompressionFailedError:
            raise
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            raise CompressionFailedError(
                f"ZIP作成に失敗しました: {exc}",
                archive_path=str(options.output_path),
            ) from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def check_tool_availability(self) -> tuple[bool, str | None]:
        return True, None
