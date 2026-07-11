"""
src/kaito/archive/zip_backend.py
ZIP形式バックエンド (標準ライブラリ zipfile)
関連: archive/backend.py, archive/safety.py, domain/errors.py, domain/models.py
"""

from __future__ import annotations

import locale
import zipfile
from datetime import datetime
from pathlib import Path
from collections.abc import Callable
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

    # ZIPファイル名のデコードに試すエンコーディング順
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
        """サロゲート文字 (デコード失敗の跡) が含まれるか判定"""
        for name in names:
            for c in name:
                if 0xDC80 <= ord(c) <= 0xDCFF:
                    return True
        return False

    def _try_zip_with_encodings(
        self, path: Path, operation: Callable[[zipfile.ZipFile], _T]
    ) -> _T:
        """エンコーディングフォールバック付きでZIP操作を実行"""
        last_zf: zipfile.ZipFile | None = None
        for enc in self._encoding_tries():
            try:
                zf = zipfile.ZipFile(path, "r", metadata_encoding=enc)
            except (UnicodeDecodeError, UnicodeError, LookupError):
                continue
            last_zf = zf
            names = [e.filename for e in zf.infolist()]
            if not self._has_surrogates(names):
                return operation(zf)
        # 全エンコーディングでサロゲート発生 → 最後の結果を強制採用
        if last_zf is not None:
            return operation(last_zf)
        raise ExtractionFailedError(
            "ZIPファイルを開けませんでした", archive_path=str(path)
        )

    def list_archive(self, path: Path, password: str | None = None) -> ArchiveInfo:
        def _extract_entries(zf: zipfile.ZipFile) -> ArchiveInfo:
            entries: list[ArchiveEntry] = []
            is_encrypted = False
            for info in zf.infolist():
                _ = info.filename  # デコードをトリガー
                # 暗号化フラグ: bit 0 (ZipCrypto) または bit 6 (AES)
                encrypted = bool(info.flag_bits & 0x1 or info.flag_bits & 0x40)
                if encrypted:
                    is_encrypted = True
                entries.append(
                    ArchiveEntry(
                        name=info.filename,
                        size=info.file_size,
                        compressed_size=info.compress_size,
                        modified=datetime(*info.date_time),
                        is_dir=info.filename.endswith("/"),
                        is_encrypted=encrypted,
                    )
                )
            return ArchiveInfo(
                path=path, entries=entries, is_encrypted=is_encrypted, format_name="zip"
            )

        try:
            return self._try_zip_with_encodings(path, _extract_entries)
        except (zipfile.BadZipFile, OSError) as e:
            raise ExtractionFailedError(
                f"ZIPファイルの読み込みに失敗: {e}", archive_path=str(path)
            )

    def extract(self, path: Path, options: ExtractionOptions) -> None:
        def _do_extract(zf: zipfile.ZipFile) -> None:
            if options.password is not None:
                zf.setpassword(options.password.encode("utf-8"))

            targets = options.members or [e.filename for e in zf.infolist()]
            total = len(targets)

            # 事前検証: 全エントリのパス安全性をチェック
            entries = [
                ArchiveEntry(
                    name=info.filename,
                    size=info.file_size,
                    compressed_size=info.compress_size,
                    modified=datetime(*info.date_time),
                    is_dir=info.filename.endswith("/"),
                )
                for info in zf.infolist()
                if info.filename in targets
            ]
            check_archive_safety(entries, options)

            for i, name in enumerate(targets):
                # パストラバーサル対策: 安全な出力先パスを取得
                safe_target = validate_entry_path(name, options.dest_dir)

                if name.endswith("/"):
                    safe_target.mkdir(parents=True, exist_ok=True)
                else:
                    # 安全確認済みのパスへ直接書き込み
                    source_data = zf.read(name)
                    safe_target.parent.mkdir(parents=True, exist_ok=True)
                    safe_target.write_bytes(source_data)

                if options.on_progress:
                    options.on_progress(i + 1, total, name)

        try:
            self._try_zip_with_encodings(path, _do_extract)
        except (RuntimeError, KeyError) as e:
            msg = str(e).lower()
            if "password" in msg or "pwd" in msg:
                raise InvalidPasswordError(str(path))
            raise ExtractionFailedError(
                f"展開に失敗しました: {e}", archive_path=str(path)
            )
        except (zipfile.BadZipFile, OSError) as e:
            raise ExtractionFailedError(
                f"ZIPファイルの展開に失敗: {e}", archive_path=str(path)
            )

    def create(self, options: CompressionOptions) -> None:
        # 出力ファイルが入力ソースに含まれていないかチェック
        output_resolved = options.output_path.resolve()
        for src in options.sources:
            src_resolved = src.resolve()
            if src_resolved == output_resolved or (
                src_resolved.is_dir() and output_resolved.is_relative_to(src_resolved)
            ):
                raise CompressionFailedError(
                    "出力アーカイブが圧縮対象に含まれています",
                    archive_path=str(options.output_path),
                )

        # 圧縮レベル検証
        level = options.compression_level
        if not 0 <= level <= 9:
            raise CompressionFailedError("圧縮レベルは0〜9で指定してください")

        total_files = 0
        for s in options.sources:
            if s.is_dir():
                total_files += sum(1 for f in s.rglob("*") if f.is_file())
            else:
                total_files += 1

        done = 0

        try:
            with zipfile.ZipFile(
                options.output_path, "w", zipfile.ZIP_DEFLATED, compresslevel=level
            ) as zf:
                for source in options.sources:
                    if source.is_dir():
                        for f in source.rglob("*"):
                            if f.is_file():
                                arcname = f.relative_to(source.parent)
                                zf.write(f, str(arcname))
                                done += 1
                                if options.on_progress:
                                    options.on_progress(done, total_files, f.name)
                            elif f.is_dir():
                                arcname = f.relative_to(source.parent)
                                zi = zipfile.ZipInfo(str(arcname) + "/")
                                zf.writestr(zi, b"")
                    else:
                        zf.write(source, source.name)
                        done += 1
                        if options.on_progress:
                            options.on_progress(done, total_files, source.name)
        except (OSError, RuntimeError) as e:
            # 失敗時は出力ファイルを削除
            if options.output_path.exists():
                try:
                    options.output_path.unlink()
                except OSError:
                    pass
            raise CompressionFailedError(
                f"ZIP作成に失敗しました: {e}", archive_path=str(options.output_path)
            )

    def read_entry(
        self, path: Path, entry_name: str, password: Optional[str] = None
    ) -> Optional[bytes]:
        """アーカイブ内の1エントリを読み込む (プレビュー用)"""

        def _read(zf: zipfile.ZipFile) -> bytes:
            if password is not None:
                zf.setpassword(password.encode("utf-8"))
            return zf.read(entry_name)

        try:
            return self._try_zip_with_encodings(path, _read)
        except (KeyError, RuntimeError, zipfile.BadZipFile):
            return None

    def check_tool_availability(self) -> tuple[bool, str | None]:
        return True, None  # zipfileは標準ライブラリなので常に利用可能
