"""
src/kaito/archive/zip_backend.py
ZIP形式バックエンド (標準ライブラリ zipfile)
関連: archive/safety.py, domain/errors.py, domain/models.py
"""

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

from kaito.archive.safety import check_archive_safety, validate_entry_path
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
    """ZIP形式のアーカイブ操作 (zipfile使用)"""

    name = "zip"
    supported_extensions = frozenset({".zip"})
    can_create = True
    can_extract = True
    can_list = True
    supports_password = True

    _FALLBACK_ENCODINGS = [
        "utf-8",
        "cp932",
        "gbk",
        "cp949",
        "shift_jis",
        "euc-kr",
    ]

    def _get_system_encoding(self) -> str:
        try:
            return locale.getencoding()
        except Exception:
            return "utf-8"

    def _encoding_tries(self) -> list[str]:
        tries = ["utf-8"]
        for enc in self._FALLBACK_ENCODINGS:
            if enc.lower() not in ("utf-8", "utf8"):
                tries.append(enc)
        sys_enc = self._get_system_encoding()
        if sys_enc.lower() not in (e.lower() for e in tries):
            tries.append(sys_enc)
        return tries

    def _has_surrogates(self, names: list[str]) -> bool:
        return any(0xDC80 <= ord(c) <= 0xDCFF for name in names for c in name)

    def _try_zip_with_encodings(
        self, path: Path, operation: Callable[[zipfile.ZipFile], _T]
    ) -> _T:
        last_zf: zipfile.ZipFile | None = None
        for enc in self._encoding_tries():
            try:
                zf = zipfile.ZipFile(path, "r", metadata_encoding=enc)
            except (UnicodeDecodeError, UnicodeError, LookupError):
                continue
            last_zf = zf
            try:
                names = [e.filename for e in zf.infolist()]
                if not self._has_surrogates(names):
                    return operation(zf)
            finally:
                zf.close()
        if last_zf is not None:
            # last_zf は上でclose済みなので、最後のエンコーディングで再度開く。
            enc = self._encoding_tries()[-1]
            with zipfile.ZipFile(path, "r", metadata_encoding=enc) as zf:
                return operation(zf)
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

        def _extract_entries(zf: zipfile.ZipFile) -> ArchiveInfo:
            entries = [self._entry_from_info(info) for info in zf.infolist()]
            return ArchiveInfo(
                path=path,
                entries=entries,
                is_encrypted=any(e.is_encrypted for e in entries),
                format_name="zip",
            )

        try:
            return self._try_zip_with_encodings(path, _extract_entries)
        except (zipfile.BadZipFile, OSError) as e:
            raise ExtractionFailedError(
                f"ZIPファイルの読み込みに失敗: {e}", archive_path=str(path)
            ) from e

    def extract(self, path: Path, options: ExtractionOptions) -> None:
        def _do_extract(zf: zipfile.ZipFile) -> None:
            if options.password is not None:
                zf.setpassword(options.password.encode("utf-8"))

            infos_by_name = {info.filename: info for info in zf.infolist()}
            targets = options.members or list(infos_by_name)
            try:
                infos = [infos_by_name[name] for name in targets]
            except KeyError as e:
                raise ExtractionFailedError(
                    f"指定されたエントリが見つかりません: {e.args[0]}",
                    archive_path=str(path),
                ) from e

            entries = [self._entry_from_info(info) for info in infos]
            check_archive_safety(entries, options)

            for i, info in enumerate(infos):
                safe_target = validate_entry_path(info.filename, options.dest_dir)
                if info.is_dir():
                    safe_target.mkdir(parents=True, exist_ok=True)
                else:
                    safe_target.parent.mkdir(parents=True, exist_ok=True)
                    # extract()を使わず、検証済みパスへストリームコピーする。
                    with zf.open(info, "r") as source, safe_target.open("wb") as target:
                        while chunk := source.read(1024 * 1024):
                            target.write(chunk)
                if options.on_progress:
                    options.on_progress(i + 1, len(infos), info.filename)

        try:
            self._try_zip_with_encodings(path, _do_extract)
        except InvalidPasswordError:
            raise
        except RuntimeError as e:
            msg = str(e).lower()
            if "password" in msg or "pwd" in msg:
                raise InvalidPasswordError(str(path)) from e
            raise ExtractionFailedError(
                f"展開に失敗しました: {e}", archive_path=str(path)
            ) from e
        except (zipfile.BadZipFile, OSError) as e:
            raise ExtractionFailedError(
                f"ZIPファイルの展開に失敗: {e}", archive_path=str(path)
            ) from e

    def create(self, options: CompressionOptions) -> None:
        output_resolved = options.output_path.resolve(strict=False)
        for src in options.sources:
            src_resolved = src.resolve(strict=False)
            if src_resolved == output_resolved or (
                src_resolved.is_dir() and output_resolved.is_relative_to(src_resolved)
            ):
                raise CompressionFailedError(
                    "出力アーカイブが圧縮対象に含まれています",
                    archive_path=str(options.output_path),
                )

        level = options.compression_level
        if not 0 <= level <= 9:
            raise CompressionFailedError("圧縮レベルは0〜9で指定してください")
        if options.password:
            raise CompressionFailedError(
                "標準ZIPバックエンドは暗号化ZIPの作成に対応していません",
                archive_path=str(options.output_path),
            )

        total_files = sum(
            sum(1 for f in source.rglob("*") if f.is_file())
            if source.is_dir()
            else 1
            for source in options.sources
        )
        options.output_path.parent.mkdir(parents=True, exist_ok=True)

        tmp_path: Optional[Path] = None
        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{options.output_path.stem}.",
                suffix=".tmp.zip",
                dir=options.output_path.parent,
            )
            os.close(fd)
            tmp_path = Path(tmp_name)
            done = 0
            with zipfile.ZipFile(
                tmp_path, "w", zipfile.ZIP_DEFLATED, compresslevel=level
            ) as zf:
                for source in options.sources:
                    if source.is_dir():
                        for item in source.rglob("*"):
                            arcname = item.relative_to(source.parent).as_posix()
                            if item.is_symlink():
                                raise CompressionFailedError(
                                    f"シンボリックリンクは圧縮できません: {item}"
                                )
                            if item.is_file():
                                zf.write(item, arcname)
                                done += 1
                                if options.on_progress:
                                    options.on_progress(done, total_files, item.name)
                            elif item.is_dir():
                                zf.writestr(zipfile.ZipInfo(arcname.rstrip("/") + "/"), b"")
                    else:
                        if source.is_symlink():
                            raise CompressionFailedError(
                                f"シンボリックリンクは圧縮できません: {source}"
                            )
                        zf.write(source, source.name)
                        done += 1
                        if options.on_progress:
                            options.on_progress(done, total_files, source.name)

            with zipfile.ZipFile(tmp_path, "r") as verify:
                bad = verify.testzip()
                if bad is not None:
                    raise CompressionFailedError(f"作成したZIPの検証に失敗しました: {bad}")
            os.replace(tmp_path, options.output_path)
            tmp_path = None
        except CompressionFailedError:
            raise
        except (OSError, RuntimeError, zipfile.BadZipFile) as e:
            raise CompressionFailedError(
                f"ZIP作成に失敗しました: {e}", archive_path=str(options.output_path)
            ) from e
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    def read_entry(
        self, path: Path, entry_name: str, password: Optional[str] = None
    ) -> Optional[bytes]:
        def _read(zf: zipfile.ZipFile) -> bytes:
            info = zf.getinfo(entry_name)
            if self._is_link(info) or info.file_size > 10 * 1024 * 1024:
                raise ValueError("preview entry is unsafe or too large")
            if password is not None:
                zf.setpassword(password.encode("utf-8"))
            return zf.read(info)

        try:
            return self._try_zip_with_encodings(path, _read)
        except (KeyError, RuntimeError, ValueError, zipfile.BadZipFile):
            return None

    def check_tool_availability(self) -> tuple[bool, str | None]:
        return True, None
