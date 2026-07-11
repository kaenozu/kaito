"""
src/kaito/archive/sevenzip_backend.py
同梱7-Zip CLIを使用するRAR/7zバックエンド。
RARは一覧・展開のみ、7zは一覧・展開・作成に対応する。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence

from kaito.domain.errors import (
    CancelledError,
    CompressionFailedError,
    ExternalToolNotFoundError,
    ExtractionFailedError,
    InvalidPasswordError,
    PasswordRequiredError,
    UnsafeArchiveError,
)
from kaito.domain.models import (
    ArchiveEntry,
    ArchiveInfo,
    CompressionOptions,
    ExtractionOptions,
    check_archive_safety,
    is_reparse_or_link,
    validate_entry_path,
)

SEVENZIP_VERSION = "26.02"
SEVENZIP_URL = "https://github.com/ip7z/7zip/releases/tag/26.02"
SEVENZIP_EXE_SHA256 = "83967f1b02b43c4efeda302795722c809e0e81b8307de73558d10484d5676a7d"
SEVENZIP_DLL_SHA256 = "69fd4df057985c40e510e2fac182881c7f85e90aa13ec703f763a8fdb2ce61f8"
SEVENZIP_LICENSE = (
    "GNU LGPL + BSD 2-Clause + BSD 3-Clause + unRAR restriction. "
    "See bundled/7-ZIP-LICENSE.txt and THIRD_PARTY_NOTICES.md."
)


def redact_command(args: Sequence[str]) -> list[str]:
    """ログや例外表示用にコマンドライン上の秘密情報を伏せる。"""
    redacted: list[str] = []
    hide_next = False
    for arg in args:
        if hide_next:
            redacted.append("***")
            hide_next = False
        elif arg in {"-p", "--password"}:
            redacted.append(arg)
            hide_next = True
        elif arg.startswith("-p") and len(arg) > 2:
            redacted.append("-p***")
        elif arg.startswith("--password="):
            redacted.append("--password=***")
        else:
            redacted.append(arg)
    return redacted


def _redact_text(text: str, password: Optional[str]) -> str:
    if password:
        return text.replace(password, "***")
    return text


class SevenZipBackend:
    """7-Zip CLIを使用したRAR/7z操作。"""

    name = "7z"
    supported_extensions = frozenset({".7z", ".rar"})
    can_create = True
    can_extract = True
    can_list = True
    supports_password = True

    _COMMON_PATHS = [
        Path("C:/Program Files/7-Zip/7z.exe"),
        Path("C:/Program Files (x86)/7-Zip/7z.exe"),
    ]
    _BUNDLED_NAME = "7z.exe"

    def __init__(self, cancel_event: Optional[threading.Event] = None) -> None:
        self._tool_path: Optional[Path] = None
        self._tool_source: Optional[str] = None
        self._current_process: Optional[subprocess.Popen[str]] = None
        self._process_lock = threading.Lock()
        self._cancel_event = cancel_event or threading.Event()

    @staticmethod
    def _is_frozen() -> bool:
        return bool(getattr(sys, "frozen", False))

    def _bundled_dir(self) -> Optional[Path]:
        """PyInstallerまたは開発ツリー内のbundledディレクトリを返す。"""
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / "bundled"
        try:
            # .../repo/src/kaito/archive/sevenzip_backend.py -> repo/bundled
            return Path(__file__).resolve().parents[3] / "bundled"
        except (IndexError, NameError, OSError):
            return None

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _verify_bundled_tool(self, path: Path) -> None:
        actual = self._sha256(path)
        if actual.lower() != SEVENZIP_EXE_SHA256.lower():
            raise ExternalToolNotFoundError(
                "7z",
                "同梱7-Zipの整合性検証に失敗しました。kaitoを再インストールしてください。",
            )
        dll = path.with_name("7z.dll")
        if not dll.is_file() or self._sha256(dll).lower() != SEVENZIP_DLL_SHA256.lower():
            raise ExternalToolNotFoundError(
                "7z.dll",
                "同梱7-Zip DLLの整合性検証に失敗しました。kaitoを再インストールしてください。",
            )

    def _find_tool(self) -> Path:
        if self._tool_path is not None and self._tool_path.is_file():
            return self._tool_path

        frozen = self._is_frozen()
        bundled_dir = self._bundled_dir()
        bundled = bundled_dir / self._BUNDLED_NAME if bundled_dir else None
        if bundled is not None and bundled.is_file():
            self._verify_bundled_tool(bundled)
            self._tool_path = bundled
            self._tool_source = "bundled"
            return bundled

        # 配布EXEではシステム版へフォールバックしない。
        if frozen:
            raise ExternalToolNotFoundError(
                "7z",
                "同梱7-Zipが見つかりません。kaitoを再インストールしてください。",
            )

        explicit = os.environ.get("KAITO_7Z_PATH")
        if explicit:
            candidate = Path(explicit)
            if candidate.is_file():
                self._tool_path = candidate
                self._tool_source = "explicit"
                return candidate
            raise ExternalToolNotFoundError(
                "7z", f"KAITO_7Z_PATHのファイルが見つかりません: {candidate}"
            )

        # システム版は開発・診断用途で明示許可された場合だけ使用する。
        if os.environ.get("KAITO_ALLOW_SYSTEM_7Z") == "1":
            for candidate in self._COMMON_PATHS:
                if candidate.is_file():
                    self._tool_path = candidate
                    self._tool_source = "system"
                    return candidate
            found = shutil.which("7z")
            if found:
                self._tool_path = Path(found)
                self._tool_source = "system"
                return self._tool_path

        raise ExternalToolNotFoundError(
            "7z",
            "同梱7-Zipが見つかりません。リポジトリのbundledディレクトリを確認してください。",
        )

    def check_tool_availability(self) -> tuple[bool, Optional[str]]:
        try:
            self._find_tool()
            return True, None
        except ExternalToolNotFoundError as exc:
            return False, str(exc)

    def backend_info(self) -> dict[str, Any]:
        tool = self._find_tool()
        actual = self._sha256(tool)
        result = self._run_7z(["i"], timeout=10)
        version = SEVENZIP_VERSION
        for line in result.stdout.splitlines():
            if "7-Zip" in line:
                for token in line.split():
                    if token[:1].isdigit() and "." in token:
                        version = token
                        break
                break
        expected = SEVENZIP_EXE_SHA256 if self._tool_source == "bundled" else None
        return {
            "available": True,
            "source": self._tool_source or "unknown",
            "path": str(tool),
            "version": version,
            "sha256": actual,
            "expected_sha256": expected,
            "integrity": "ok" if expected is None or actual == expected else "mismatch",
        }

    def supports_format(self, extension: str) -> bool:
        return extension.lower() in self.supported_extensions

    def supports_creation(self, extension: str) -> bool:
        return extension.lower() == ".7z"

    def _set_current_process(self, process: Optional[subprocess.Popen[str]]) -> None:
        with self._process_lock:
            self._current_process = process

    def _terminate_process(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                pass
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except (OSError, subprocess.SubprocessError):
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)

    def _run_7z(
        self,
        args: list[str],
        *,
        password: Optional[str] = None,
        timeout: float = 300,
    ) -> subprocess.CompletedProcess[str]:
        """非対話で7-Zipを実行し、キャンセルを処理中も監視する。"""
        self._check_cancelled()
        tool = self._find_tool()
        cmd = [str(tool), *args, "-y"]
        if password is not None:
            # 7-Zip CLIの仕様上、パスワードはプロセス引数へ渡す必要がある。
            # 返却値・ログ・例外では必ずredactする。
            cmd.append(f"-p{password}")

        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        process: Optional[subprocess.Popen[str]] = None
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )
            self._set_current_process(process)
            while True:
                if self._cancel_event.is_set():
                    self._terminate_process(process)
                    raise CancelledError()
                elapsed = time.monotonic() - started
                if elapsed >= timeout:
                    self._terminate_process(process)
                    raise ExtractionFailedError("7-Zipの処理がタイムアウトしました")
                try:
                    stdout, stderr = process.communicate(timeout=min(0.2, timeout - elapsed))
                    break
                except subprocess.TimeoutExpired:
                    continue

            return subprocess.CompletedProcess(
                args=redact_command(cmd),
                returncode=process.returncode,
                stdout=_redact_text(stdout or "", password),
                stderr=_redact_text(stderr or "", password),
            )
        finally:
            if process is not None and process.poll() is None:
                self._terminate_process(process)
            self._set_current_process(None)

    def _check_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise CancelledError()

    @staticmethod
    def _parse_slt_output(text: str) -> list[dict[str, str]]:
        """7z l -sltのKey = Valueブロックを解析する。"""
        entries: list[dict[str, str]] = []
        current: dict[str, str] = {}
        in_entries = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("---") and stripped.endswith("---"):
                in_entries = True
                current = {}
                continue
            if not in_entries:
                continue
            if not stripped:
                if current:
                    entries.append(current)
                    current = {}
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                current[key.strip()] = value.strip()
        if current:
            entries.append(current)
        return entries

    def _entry_from_slt(self, data: dict[str, str]) -> Optional[ArchiveEntry]:
        path = data.get("Path")
        if not path:
            return None
        try:
            size = int(data.get("Size", "0").strip() or "0")
            packed = int(data.get("Packed Size", "0").strip() or "0")
        except ValueError as exc:
            raise ExtractionFailedError(f"不正なサイズ情報です: {path}") from exc

        modified = datetime.fromtimestamp(0)
        modified_str = data.get("Modified", "")
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                modified = datetime.strptime(modified_str, pattern)
                break
            except ValueError:
                continue

        link_target = data.get("Symbolic Link") or data.get("Hard Link")
        attributes = data.get("Attributes", "").lower()
        is_link = bool(link_target) or "lrwx" in attributes or data.get("Reparse", "-") == "+"
        return ArchiveEntry(
            name=path.replace("\\", "/"),
            size=size,
            compressed_size=packed,
            modified=modified,
            is_dir=data.get("Folder", "-") == "+",
            is_encrypted=data.get("Encrypted", "-") == "+",
            is_link=is_link,
            link_target=link_target,
        )

    @staticmethod
    def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
        return f"{result.stderr}\n{result.stdout}".strip()

    def _raise_list_error(
        self,
        path: Path,
        password: Optional[str],
        result: subprocess.CompletedProcess[str],
    ) -> None:
        combined = self._combined_output(result).lower()
        if "wrong password" in combined or "data error in encrypted file" in combined:
            if password is None:
                raise PasswordRequiredError(str(path))
            raise InvalidPasswordError(str(path))
        if "password" in combined and password is None:
            raise PasswordRequiredError(str(path))
        if "cannot open the file as archive" in combined or "is not archive" in combined:
            raise ExtractionFailedError(
                f"ファイルをアーカイブとして開けません: {path.name}",
                archive_path=str(path),
            )
        raise ExtractionFailedError(
            f"7-Zipエラー (exit {result.returncode}): {self._combined_output(result)[:200]}",
            archive_path=str(path),
        )

    def list_archive(self, path: Path, password: Optional[str] = None) -> ArchiveInfo:
        self._check_cancelled()
        result = self._run_7z(["l", "-slt", str(path)], password=password)
        if result.returncode != 0:
            self._raise_list_error(path, password, result)

        entries_data = self._parse_slt_output(result.stdout)
        entries: list[ArchiveEntry] = []
        for data in entries_data:
            entry = self._entry_from_slt(data)
            if entry is not None:
                entries.append(entry)
        if not entries and entries_data:
            raise ExtractionFailedError(
                "アーカイブ一覧の解析に失敗しました",
                archive_path=str(path),
            )
        return ArchiveInfo(
            path=path,
            entries=entries,
            is_encrypted=any(e.is_encrypted for e in entries),
            format_name=path.suffix.lower().lstrip("."),
        )

    @staticmethod
    def _ensure_no_reparse_ancestors(path: Path) -> None:
        candidate = path
        while not candidate.exists() and candidate.parent != candidate:
            candidate = candidate.parent
        for existing in (candidate, *candidate.parents):
            if is_reparse_or_link(existing):
                raise UnsafeArchiveError(
                    f"展開先の親ディレクトリにリンクまたはreparse pointがあります: {existing}"
                )

    def _validate_staging(self, staging: Path, options: ExtractionOptions) -> None:
        count = 0
        total = 0
        for item in staging.rglob("*"):
            relative = item.relative_to(staging).as_posix()
            validate_entry_path(relative, staging)
            if is_reparse_or_link(item):
                raise UnsafeArchiveError(f"リンクが展開されました: {relative}")
            count += 1
            if count > options.max_entries:
                raise UnsafeArchiveError("展開後のエントリ数が上限を超えました")
            if item.is_file():
                size = item.stat().st_size
                if size > options.max_file_size:
                    raise UnsafeArchiveError(f"展開後のファイルサイズが上限を超えました: {relative}")
                total += size
                if total > options.max_total_size:
                    raise UnsafeArchiveError("展開後の合計サイズが上限を超えました")

    def _merge_staging(self, staging: Path, dest: Path) -> None:
        self._ensure_no_reparse_ancestors(dest)
        dest.mkdir(parents=True, exist_ok=True)
        items = sorted(staging.rglob("*"), key=lambda p: (not p.is_dir(), len(p.parts)))
        for item in items:
            relative = item.relative_to(staging).as_posix()
            target = validate_entry_path(relative, dest)
            self._ensure_no_reparse_ancestors(target.parent)
            if item.is_dir():
                if target.exists() and not target.is_dir():
                    raise ExtractionFailedError(f"展開先に同名ファイルがあります: {relative}")
                target.mkdir(parents=True, exist_ok=True)
            else:
                if target.exists():
                    raise ExtractionFailedError(f"展開先に同名ファイルがあります: {relative}")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(item), str(target))

    def extract(self, path: Path, options: ExtractionOptions) -> None:
        self._check_cancelled()
        info = self.list_archive(path, password=options.password)
        selected = info.entries
        if options.members is not None:
            wanted = set(options.members)
            selected = [entry for entry in info.entries if entry.name in wanted]
        check_archive_safety(selected, options)

        with tempfile.TemporaryDirectory(prefix="kaito_extract_") as temp_dir:
            staging = Path(temp_dir)
            args = ["x", str(path), f"-o{staging}"]
            if options.members:
                args.extend(options.members)
            timeout = min(3600.0, max(60.0, options.max_total_size / (10 * 1024 * 1024)))
            result = self._run_7z(args, password=options.password, timeout=timeout)
            if result.returncode != 0:
                combined = self._combined_output(result).lower()
                if "wrong password" in combined or "data error in encrypted file" in combined:
                    if options.password is None:
                        raise PasswordRequiredError(str(path))
                    raise InvalidPasswordError(str(path))
                if "crc failed" in combined or "data error" in combined:
                    raise ExtractionFailedError(
                        f"データが破損しています: {path.name}", archive_path=str(path)
                    )
                raise ExtractionFailedError(
                    f"展開に失敗しました: {path.name}", archive_path=str(path)
                )
            self._check_cancelled()
            self._validate_staging(staging, options)
            self._merge_staging(staging, options.dest_dir)

        if options.on_progress and selected:
            options.on_progress(len(selected), len(selected), path.name)

    def create(self, options: CompressionOptions) -> None:
        self._check_cancelled()
        ext = options.output_path.suffix.lower()
        if not self.supports_creation(ext):
            raise CompressionFailedError(
                f"{ext}形式の作成はサポートされていません",
                archive_path=str(options.output_path),
            )

        output = options.output_path.resolve(strict=False)
        for source in options.sources:
            resolved = source.resolve(strict=False)
            if resolved == output or (resolved.is_dir() and output.is_relative_to(resolved)):
                raise CompressionFailedError(
                    "出力アーカイブが圧縮対象に含まれています",
                    archive_path=str(options.output_path),
                )
            if source.is_symlink():
                raise CompressionFailedError(f"シンボリックリンクは圧縮できません: {source}")

        output.parent.mkdir(parents=True, exist_ok=True)
        level = max(0, min(9, options.compression_level))
        seven_level = {0: 0, 1: 1, 2: 3, 3: 3, 4: 5, 5: 5, 6: 5, 7: 7, 8: 7, 9: 9}[level]

        with tempfile.TemporaryDirectory(prefix=".kaito_7z_", dir=output.parent) as tmp_dir:
            tmpout = Path(tmp_dir) / output.name
            args = ["a", f"-mx={seven_level}", str(tmpout)]
            if options.password:
                args.append("-mhe=on")
            args.extend(str(source) for source in options.sources)
            result = self._run_7z(args, password=options.password)
            if result.returncode != 0:
                raise CompressionFailedError(
                    f"7z作成に失敗しました (exit {result.returncode})",
                    archive_path=str(options.output_path),
                )
            self._check_cancelled()
            verify = self._run_7z(
                ["t", str(tmpout)], password=options.password, timeout=300
            )
            if verify.returncode != 0:
                raise CompressionFailedError(
                    "作成したアーカイブの検証に失敗しました",
                    archive_path=str(options.output_path),
                )
            os.replace(tmpout, output)

    def read_entry(
        self,
        path: Path,
        entry_name: str,
        password: Optional[str] = None,
    ) -> Optional[bytes]:
        self._check_cancelled()
        info = self.list_archive(path, password=password)
        entry = next((item for item in info.entries if item.name == entry_name), None)
        if entry is None or entry.is_dir or entry.is_link or entry.size > 10 * 1024 * 1024:
            return None

        with tempfile.TemporaryDirectory(prefix="kaito_preview_") as temp_dir:
            staging = Path(temp_dir)
            result = self._run_7z(
                ["x", str(path), f"-o{staging}", entry_name, "-aos"],
                password=password,
            )
            if result.returncode != 0:
                return None
            target = validate_entry_path(entry_name, staging)
            if not target.is_file() or is_reparse_or_link(target):
                return None
            if target.stat().st_size > 10 * 1024 * 1024:
                return None
            return target.read_bytes()
