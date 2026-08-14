"""src/kaito/archive/dll_backend.py

同梱 7z.dll (26.02) を IInArchive 経由で直接使う読み取り系バックエンド。

zip / 7z / rar の一覧・展開・プレビュー読み出し・整合性検査を単一バックエンド
で処理する。パスワードはプロセス内 (ICryptoGetTextPassword / BSTR) で供給され、
読み取り処理中に subprocess を一切生まない (CLI の -p<password> 引数露出なし)。

作成 (圧縮) は対象外: 平文 ZIP は zip_backend.ZipBackend (zipfile)、
暗号化 ZIP / 7z は sevenzip_backend.SevenZipBackend (7z.exe CLI) が担う。
"""

from __future__ import annotations

import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from kaito.archive.inspection import IntegrityCheckResult
from kaito.archive.safety import (
    check_archive_safety,
    merge_staging_tree,
    validate_entry_path,
    validate_staging_tree,
)
from kaito.archive.sevenzip_backend import (
    SEVENZIP_DLL_SHA256,
    SEVENZIP_VERSION,
)
from kaito.archive.sevenzip_dll import (
    DllExtractError,
    DllOpenFailedError,
    DllPasswordError,
    SevenZipDll,
    SevenZipDllError,
    S_FALSE,
    kDataError,
    kOK,
    kUnsupportedMethod,
    kWrongPassword,
)
from kaito.domain.errors import (
    CancelledError,
    ExtractionFailedError,
    ExternalToolNotFoundError,
    InvalidPasswordError,
    PasswordRequiredError,
)
from kaito.domain.models import (
    ArchiveEntry,
    ArchiveInfo,
    ExtractionOptions,
    SafetyLimits,
)

# フォーマット署名 (破損/未認識とヘッダー暗号化の切り分けに使用)
_SIGNATURES = {
    ".zip": b"PK",
    ".7z": b"7z\xbc\xaf\x27\x1c",
    ".rar": b"Rar!\x1a\x07",
}

_EPOCH = datetime(1970, 1, 1)


def _signature_matches(path: Path, extension: str) -> bool:
    """ファイル先頭が対応フォーマットの署名と一致するかを返す。"""
    signature = _SIGNATURES.get(extension.lower())
    if signature is None:
        return False
    try:
        with path.open("rb") as stream:
            return stream.read(len(signature)) == signature
    except OSError:
        return False


class DllArchiveBackend:
    """7z.dll (IInArchive) を使用する読み取り専用バックエンド。"""

    name = "7z-dll"
    supported_extensions = frozenset({".zip", ".7z", ".rar"})
    can_create = False
    can_extract = True
    can_list = True
    supports_password = True

    def __init__(
        self,
        cancel_event: Optional[threading.Event] = None,
        *,
        preview_max_size: Optional[int] = None,
    ) -> None:
        self._cancel_event = cancel_event or threading.Event()
        self._preview_max_size = (
            preview_max_size
            if preview_max_size is not None
            else SafetyLimits().preview_max_size
        )
        self._dll_path: Optional[Path] = None
        self._dll: Optional[SevenZipDll] = None

    # ------------------------------------------------------------------
    # ツール検出・整合性検証
    # ------------------------------------------------------------------

    @staticmethod
    def _is_frozen() -> bool:
        import sys

        return bool(getattr(sys, "frozen", False))

    def _bundled_dir(self) -> Optional[Path]:
        import sys

        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / "bundled"
        try:
            return Path(__file__).resolve().parents[3] / "bundled"
        except (IndexError, NameError, OSError):
            return None

    @staticmethod
    def _sha256(path: Path) -> str:
        import hashlib

        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _find_dll(self) -> Path:
        """同梱 7z.dll を検出し、ピン留め SHA-256 と照合して返す。"""
        if self._dll_path is not None and self._dll_path.is_file():
            if self._sha256(self._dll_path).lower() != SEVENZIP_DLL_SHA256:
                raise ExternalToolNotFoundError(
                    "7z.dll",
                    "同梱7-Zip DLLの整合性検証に失敗しました。kaitoを再インストールしてください。",
                )
            return self._dll_path

        bundled_dir = self._bundled_dir()
        bundled = bundled_dir / "7z.dll" if bundled_dir else None
        if bundled is not None and bundled.is_file():
            if self._sha256(bundled).lower() != SEVENZIP_DLL_SHA256:
                raise ExternalToolNotFoundError(
                    "7z.dll",
                    "同梱7-Zip DLLの整合性検証に失敗しました。kaitoを再インストールしてください。",
                )
            self._dll_path = bundled
            return bundled

        raise ExternalToolNotFoundError(
            "7z.dll",
            "同梱7-Zip DLLが見つかりません。kaitoを再インストールしてください。",
        )

    def _get_dll(self) -> SevenZipDll:
        if self._dll is None:
            self._dll = SevenZipDll(self._find_dll())
        return self._dll

    def check_tool_availability(self) -> tuple[bool, Optional[str]]:
        try:
            self._find_dll()
            return True, None
        except ExternalToolNotFoundError as exc:
            return False, str(exc)

    def backend_info(self) -> dict[str, Any]:
        dll_path = self._find_dll()
        actual_hash = self._sha256(dll_path)
        return {
            "available": True,
            "source": "bundled",
            "path": str(dll_path),
            "version": SEVENZIP_VERSION,
            "sha256": actual_hash,
            "expected_sha256": SEVENZIP_DLL_SHA256,
            "integrity": ("ok" if actual_hash == SEVENZIP_DLL_SHA256 else "mismatch"),
        }

    def supports_format(self, extension: str) -> bool:
        return extension.lower() in self.supported_extensions

    def supports_creation(self, extension: str) -> bool:
        del extension
        return False

    def _check_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise CancelledError()

    def _handler_for(self, extension: str) -> str:
        return extension.lower().lstrip(".")

    # ------------------------------------------------------------------
    # Open 失敗の解釈 (破損 vs ヘッダー暗号化)
    # ------------------------------------------------------------------

    def _open(self, path: Path, password: Optional[str]) -> Any:
        """アーカイブを開く。失敗時はドメイン例外へ変換する。

        - 署名が一致しない → ExtractionFailedError (破損・未認識)
        - 署名が一致するのに開けない → ヘッダー暗号化のパスワード不足とみなす
        """
        extension = path.suffix.lower()
        try:
            return self._get_dll().open_archive(
                path,
                self._handler_for(extension),
                password=password,
                cancel_check=self._check_cancelled,
            )
        except DllOpenFailedError as exc:
            if exc.hresult == S_FALSE and _signature_matches(path, extension):
                if password is None:
                    raise PasswordRequiredError(str(path)) from exc
                raise InvalidPasswordError(str(path)) from exc
            raise ExtractionFailedError(
                f"ファイルをアーカイブとして開けません: {path.name}",
                archive_path=str(path),
            ) from exc
        except FileNotFoundError as exc:
            raise ExtractionFailedError(
                f"ファイルが見つかりません: {path.name}", archive_path=str(path)
            ) from exc
        except SevenZipDllError as exc:
            raise ExtractionFailedError(
                f"アーカイブを開けませんでした: {exc}", archive_path=str(path)
            ) from exc

    # ------------------------------------------------------------------
    # エントリ変換
    # ------------------------------------------------------------------

    def _entry_from_item(self, item: Any, path: Path) -> ArchiveEntry:
        name = item.name.replace("\\", "/")
        # 旧 zipfile バックエンドはディレクトリ名の末尾に / を付けて返していた
        if item.is_dir and not name.endswith("/"):
            name += "/"
        modified = item.modified if item.modified is not None else _EPOCH
        return ArchiveEntry(
            name=name,
            size=item.size,
            compressed_size=item.packed_size,
            modified=modified,
            is_dir=item.is_dir,
            is_encrypted=item.is_encrypted,
            is_link=item.is_link,
        )

    # ------------------------------------------------------------------
    # 一覧
    # ------------------------------------------------------------------

    def list_archive(self, path: Path, password: Optional[str] = None) -> ArchiveInfo:
        self._check_cancelled()
        with self._open(path, password) as opened:
            items = opened.list_items()
        entries = [self._entry_from_item(item, path) for item in items]
        return ArchiveInfo(
            path=path,
            entries=entries,
            is_encrypted=any(entry.is_encrypted for entry in entries),
            format_name=path.suffix.lower().lstrip("."),
        )

    # ------------------------------------------------------------------
    # 展開
    # ------------------------------------------------------------------

    def _raise_for_operation_result(
        self,
        entry: ArchiveEntry,
        result: int,
        path: Path,
        password: Optional[str],
    ) -> None:
        """単一ファイルの操作結果コードをドメイン例外へ変換する。

        RAR ハンドラは暗号化エントリでパスワード不足/誤りを kUnsupportedMethod
        (パスワードなし) や kDataError (誤パスワード) で報告するため、
        暗号化エントリに限りパスワード系とみなす。
        """
        if result == kOK:
            return
        if result == kWrongPassword:
            if password is None:
                raise PasswordRequiredError(str(path))
            raise InvalidPasswordError(str(path))
        if result in (kDataError, kUnsupportedMethod) and entry.is_encrypted:
            if password is None:
                raise PasswordRequiredError(str(path))
            raise InvalidPasswordError(str(path))
        raise ExtractionFailedError(
            f"展開に失敗しました: {entry.name} (エラーコード {result})",
            archive_path=str(path),
        )

    def extract(self, path: Path, options: ExtractionOptions) -> None:
        self._check_cancelled()
        with self._open(path, options.password) as opened:
            items = opened.list_items()
            entries = [self._entry_from_item(item, path) for item in items]

            selected = entries
            if options.members is not None:
                wanted = set(options.members)
                selected = [entry for entry in entries if entry.name in wanted]
                if len(selected) != len(wanted):
                    missing = sorted(wanted - {entry.name for entry in selected})
                    raise ExtractionFailedError(
                        f"指定されたエントリが見つかりません: {', '.join(missing)}"
                    )

            check_archive_safety(selected, options)
            items_by_name = {item.name.replace("\\", "/"): item for item in items}

            with tempfile.TemporaryDirectory(prefix="kaito_extract_") as temporary:
                staging = Path(temporary)
                total = len(selected)
                for index, entry in enumerate(selected):
                    self._check_cancelled()
                    target = validate_entry_path(entry.name, staging)
                    if entry.is_dir:
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        item = items_by_name[entry.name]
                        with target.open("wb") as output:
                            try:
                                opened.extract_to_file(
                                    item.index,
                                    output,
                                    password=options.password,
                                )
                            except DllPasswordError as exc:
                                if options.password is None:
                                    raise PasswordRequiredError(str(path)) from exc
                                raise InvalidPasswordError(str(path)) from exc
                            except DllExtractError as exc:
                                self._raise_for_operation_result(
                                    entry, exc.operation_result, path, options.password
                                )
                    self._check_cancelled()
                    if options.on_progress:
                        options.on_progress(index + 1, total, entry.name)
                    self._check_cancelled()

                validate_staging_tree(staging, options)
                self._check_cancelled()
                merge_staging_tree(staging, options.dest_dir)

    # ------------------------------------------------------------------
    # プレビュー読み出し
    # ------------------------------------------------------------------

    def read_entry(
        self,
        path: Path,
        entry_name: str,
        password: Optional[str] = None,
    ) -> Optional[bytes]:
        self._check_cancelled()
        with self._open(path, password) as opened:
            items = opened.list_items()
            entry = next(
                (item for item in items if item.name.replace("\\", "/") == entry_name),
                None,
            )
            if (
                entry is None
                or entry.is_dir
                or entry.is_link
                or entry.size > self._preview_max_size
            ):
                return None
            try:
                return opened.extract_to_memory(entry.index, password=password)
            except DllPasswordError:
                return None
            except DllExtractError:
                return None

    # ------------------------------------------------------------------
    # 整合性検査
    # ------------------------------------------------------------------

    def test_archive(
        self, path: Path, password: Optional[str] = None
    ) -> IntegrityCheckResult:
        """テストモード (展開なし) で全ファイルの CRC を検査する。"""
        self._check_cancelled()
        with self._open(path, password) as opened:
            items = opened.list_items()
            file_indices = [
                item.index for item in items if not item.is_dir and not item.is_link
            ]
            entries_by_index = {
                item.index: self._entry_from_item(item, path) for item in items
            }
            results = opened.test_indices(file_indices, password=password)

        checked = 0
        for index, result in zip(file_indices, results):
            entry = entries_by_index.get(index)
            if entry is None:
                continue
            self._raise_for_operation_result(entry, result, path, password)
            checked += 1

        if checked != len(file_indices):
            raise ExtractionFailedError(
                f"整合性検査の結果を取得できませんでした ({checked}/{len(file_indices)})",
                archive_path=str(path),
            )
        return IntegrityCheckResult(
            status="passed",
            checked_entries=checked,
            message=f"整合性検査に成功しました（{checked}ファイル、CRCエラーなし）",
        )
