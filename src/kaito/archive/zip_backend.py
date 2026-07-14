"""ZIP形式バックエンド。"""

from __future__ import annotations

import locale
import os
import stat
import tempfile
import threading
import zipfile
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Optional, TypeVar

from kaito.archive.inspection import IntegrityCheckResult
from kaito.archive.safety import (
    check_archive_safety,
    merge_staging_tree,
    validate_entry_path,
    validate_staging_tree,
)
from kaito.domain.errors import (
    CancelledError,
    CompressionFailedError,
    ExtractionFailedError,
    InvalidPasswordError,
)
from kaito.domain.models import (
    ArchiveEntry,
    ArchiveInfo,
    CompressionOptions,
    ExtractionOptions,
    is_reparse_or_link,
)

_T = TypeVar("_T")


class ZipBackend:
    """標準ライブラリzipfileを使用するZIPバックエンド。"""

    name = "zip"
    supported_extensions = frozenset({".zip"})
    can_create = True
    can_extract = True
    can_list = True
    supports_password = True

    _FALLBACK_ENCODINGS = ["utf-8", "cp932", "gbk", "cp949", "shift_jis", "euc-kr"]
    _IO_CHUNK_SIZE = 1024 * 1024

    def __init__(self, cancel_event: Optional[threading.Event] = None) -> None:
        self._cancel_event = cancel_event or threading.Event()

    def _check_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise CancelledError()

    def _get_system_encoding(self) -> str:
        try:
            return locale.getencoding()
        except Exception:
            return "utf-8"

    def _encoding_tries(self) -> list[str]:
        encodings = ["utf-8"]
        for encoding in self._FALLBACK_ENCODINGS:
            if encoding.lower() not in ("utf-8", "utf8"):
                encodings.append(encoding)
        system_encoding = self._get_system_encoding()
        if system_encoding.lower() not in (item.lower() for item in encodings):
            encodings.append(system_encoding)
        return encodings

    @staticmethod
    def _has_surrogates(names: list[str]) -> bool:
        return any(
            0xDC80 <= ord(character) <= 0xDCFF for name in names for character in name
        )

    def _try_zip_with_encodings(
        self, path: Path, operation: Callable[[zipfile.ZipFile], _T]
    ) -> _T:
        last_encoding: Optional[str] = None
        for encoding in self._encoding_tries():
            try:
                with zipfile.ZipFile(path, "r", metadata_encoding=encoding) as archive:
                    last_encoding = encoding
                    names = [entry.filename for entry in archive.infolist()]
                    if not self._has_surrogates(names):
                        return operation(archive)
            except (UnicodeDecodeError, UnicodeError, LookupError):
                continue

        if last_encoding is not None:
            with zipfile.ZipFile(path, "r", metadata_encoding=last_encoding) as archive:
                return operation(archive)
        raise ExtractionFailedError(
            "ZIPファイルを開けませんでした", archive_path=str(path)
        )

    @staticmethod
    def _is_link(info: zipfile.ZipInfo) -> bool:
        unix_mode = (info.external_attr >> 16) & 0xFFFF
        return stat.S_IFMT(unix_mode) == stat.S_IFLNK

    def _entry_from_info(self, info: zipfile.ZipInfo) -> ArchiveEntry:
        return ArchiveEntry(
            name=info.filename,
            size=info.file_size,
            compressed_size=info.compress_size,
            modified=datetime(*info.date_time),
            is_dir=info.is_dir(),
            is_encrypted=bool(info.flag_bits & 0x1 or info.flag_bits & 0x40),
            is_link=self._is_link(info),
        )

    def list_archive(self, path: Path, password: str | None = None) -> ArchiveInfo:
        del password

        def collect(archive: zipfile.ZipFile) -> ArchiveInfo:
            entries = [self._entry_from_info(info) for info in archive.infolist()]
            return ArchiveInfo(
                path=path,
                entries=entries,
                is_encrypted=any(entry.is_encrypted for entry in entries),
                format_name="zip",
            )

        try:
            return self._try_zip_with_encodings(path, collect)
        except (zipfile.BadZipFile, OSError) as exc:
            raise ExtractionFailedError(
                f"ZIPファイルの読み込みに失敗: {exc}", archive_path=str(path)
            ) from exc

    def extract(self, path: Path, options: ExtractionOptions) -> None:
        self._check_cancelled()

        def perform(archive: zipfile.ZipFile) -> None:
            if options.password is not None:
                archive.setpassword(options.password.encode("utf-8"))

            all_infos = archive.infolist()
            all_entries = [self._entry_from_info(info) for info in all_infos]
            check_archive_safety(all_entries, options)

            if options.members is None:
                infos = all_infos
            else:
                infos_by_name = {info.filename: info for info in all_infos}
                missing = [
                    name for name in options.members if name not in infos_by_name
                ]
                if missing:
                    raise ExtractionFailedError(
                        f"指定されたエントリが見つかりません: {', '.join(missing)}",
                        archive_path=str(path),
                    )
                infos = [infos_by_name[name] for name in options.members]

            with tempfile.TemporaryDirectory(prefix="kaito_zip_extract_") as temporary:
                staging = Path(temporary)
                for index, info in enumerate(infos):
                    self._check_cancelled()
                    target = validate_entry_path(info.filename, staging)
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with (
                            archive.open(info, "r") as source,
                            target.open("wb") as output,
                        ):
                            while chunk := source.read(self._IO_CHUNK_SIZE):
                                self._check_cancelled()
                                output.write(chunk)
                    self._check_cancelled()
                    if options.on_progress:
                        options.on_progress(index + 1, len(infos), info.filename)
                    self._check_cancelled()

                validate_staging_tree(staging, options)
                self._check_cancelled()
                merge_staging_tree(staging, options.dest_dir)

        try:
            self._try_zip_with_encodings(path, perform)
        except RuntimeError as exc:
            message = str(exc).lower()
            if "password" in message or "pwd" in message:
                raise InvalidPasswordError(str(path)) from exc
            raise ExtractionFailedError(
                f"展開に失敗しました: {exc}", archive_path=str(path)
            ) from exc
        except (zipfile.BadZipFile, OSError) as exc:
            raise ExtractionFailedError(
                f"ZIPファイルの展開に失敗: {exc}", archive_path=str(path)
            ) from exc

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

    def read_entry(
        self, path: Path, entry_name: str, password: Optional[str] = None
    ) -> Optional[bytes]:
        def read(archive: zipfile.ZipFile) -> bytes:
            info = archive.getinfo(entry_name)
            if self._is_link(info) or info.file_size > 10 * 1024 * 1024:
                raise ValueError("preview entry is unsafe or too large")
            if password is not None:
                archive.setpassword(password.encode("utf-8"))
            return archive.read(info)

        try:
            return self._try_zip_with_encodings(path, read)
        except (KeyError, RuntimeError, ValueError, zipfile.BadZipFile):
            return None

    def test_archive(
        self, path: Path, password: Optional[str] = None
    ) -> IntegrityCheckResult:
        """Read every ZIP member and verify CRC values without extracting."""
        self._check_cancelled()

        def verify(archive: zipfile.ZipFile) -> IntegrityCheckResult:
            if password is not None:
                archive.setpassword(password.encode("utf-8"))
            checked = 0
            for info in archive.infolist():
                self._check_cancelled()
                if info.is_dir():
                    continue
                try:
                    with archive.open(info, "r") as source:
                        while source.read(self._IO_CHUNK_SIZE):
                            self._check_cancelled()
                except RuntimeError as exc:
                    message = str(exc).lower()
                    if "password" in message or "pwd" in message:
                        raise InvalidPasswordError(str(path)) from exc
                    raise
                checked += 1
            return IntegrityCheckResult(
                status="passed",
                checked_entries=checked,
                message=f"整合性検査に成功しました（{checked}ファイル、CRCエラーなし）",
            )

        try:
            return self._try_zip_with_encodings(path, verify)
        except InvalidPasswordError:
            raise
        except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
            return IntegrityCheckResult(
                status="failed",
                checked_entries=0,
                message=f"ZIP整合性検査に失敗しました: {exc}",
            )

    def check_tool_availability(self) -> tuple[bool, str | None]:
        return True, None
