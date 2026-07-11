"""ZIP形式バックエンド。"""

from __future__ import annotations

import locale
import os
import stat
import tempfile
import zipfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Optional, TypeVar

from kaito.archive.safety import (
    check_archive_safety,
    merge_staging_tree,
    validate_entry_path,
    validate_staging_tree,
)
from kaito.domain.errors import (
    CompressionFailedError,
    ExtractionFailedError,
    InvalidPasswordError,
)
from kaito.domain.models import (
    ArchiveEntry,
    ArchiveInfo,
    CompressionOptions,
    ExtractionOptions,
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
        def perform(archive: zipfile.ZipFile) -> None:
            if options.password is not None:
                archive.setpassword(options.password.encode("utf-8"))

            infos_by_name = {info.filename: info for info in archive.infolist()}
            targets = options.members or list(infos_by_name)
            try:
                infos = [infos_by_name[name] for name in targets]
            except KeyError as exc:
                raise ExtractionFailedError(
                    f"指定されたエントリが見つかりません: {exc.args[0]}",
                    archive_path=str(path),
                ) from exc

            entries = [self._entry_from_info(info) for info in infos]
            check_archive_safety(entries, options)

            with tempfile.TemporaryDirectory(prefix="kaito_zip_extract_") as temporary:
                staging = Path(temporary)
                for index, info in enumerate(infos):
                    target = validate_entry_path(info.filename, staging)
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with (
                            archive.open(info, "r") as source,
                            target.open("wb") as output,
                        ):
                            while chunk := source.read(1024 * 1024):
                                output.write(chunk)
                    if options.on_progress:
                        options.on_progress(index + 1, len(infos), info.filename)

                validate_staging_tree(staging, options)
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

    def create(self, options: CompressionOptions) -> None:
        output_resolved = options.output_path.resolve(strict=False)
        for source in options.sources:
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

        total_files = sum(
            sum(1 for item in source.rglob("*") if item.is_file())
            if source.is_dir()
            else 1
            for source in options.sources
        )
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
                    if source.is_symlink():
                        raise CompressionFailedError(
                            f"シンボリックリンクは圧縮できません: {source}"
                        )
                    if source.is_dir():
                        for item in source.rglob("*"):
                            if item.is_symlink():
                                raise CompressionFailedError(
                                    f"シンボリックリンクは圧縮できません: {item}"
                                )
                            archive_name = item.relative_to(source.parent).as_posix()
                            if item.is_file():
                                archive.write(item, archive_name)
                                done += 1
                                if options.on_progress:
                                    options.on_progress(done, total_files, item.name)
                            elif item.is_dir():
                                archive.writestr(
                                    zipfile.ZipInfo(archive_name.rstrip("/") + "/"), b""
                                )
                    else:
                        archive.write(source, source.name)
                        done += 1
                        if options.on_progress:
                            options.on_progress(done, total_files, source.name)

            with zipfile.ZipFile(temporary_path, "r") as verification:
                bad_entry = verification.testzip()
                if bad_entry is not None:
                    raise CompressionFailedError(
                        f"作成したZIPの検証に失敗しました: {bad_entry}"
                    )
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

    def check_tool_availability(self) -> tuple[bool, str | None]:
        return True, None
