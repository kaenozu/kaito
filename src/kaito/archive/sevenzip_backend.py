"""同梱7-Zip CLIを使用するRAR/7zバックエンド。

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
    ExternalToolNotFoundError,
    ExtractionFailedError,
    InvalidPasswordError,
    PasswordRequiredError,
)
from kaito.domain.models import (
    ArchiveEntry,
    ArchiveInfo,
    CompressionOptions,
    ExtractionOptions,
    SafetyLimits,
    is_reparse_or_link,
)

# 同梱 7-Zip のピン留め定義（バージョン・URL・SHA-256）は bundled/7zip-pinned.json が唯一の管理場所
# （tools/update_7zip.ps1 と ci.yml が参照）。ここでの期待ハッシュは frozen 実行ファイルに焼き込み、
# 同梱バイナリ差し替えを検出するためのもの。JSON との一致は test_full_review_fixes.py で担保する。
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
    for argument in args:
        if hide_next:
            redacted.append("***")
            hide_next = False
        elif argument in {"-p", "--password"}:
            redacted.append(argument)
            hide_next = True
        elif argument.startswith("-p") and len(argument) > 2:
            redacted.append("-p***")
        elif argument.startswith("--password="):
            redacted.append("--password=***")
        else:
            redacted.append(argument)
    return redacted


def _redact_text(text: str, password: Optional[str]) -> str:
    return text.replace(password, "***") if password else text


class SevenZipBackend:
    """7-Zip CLIを使用したRAR/7z操作。"""

    name = "7z"
    supported_extensions = frozenset({".7z", ".rar"})
    can_create = True
    can_extract = True
    can_list = True
    supports_password = True

    _COMMON_PATHS = (
        Path("C:/Program Files/7-Zip/7z.exe"),
        Path("C:/Program Files (x86)/7-Zip/7z.exe"),
    )
    _BUNDLED_NAME = "7z.exe"

    def __init__(
        self,
        cancel_event: Optional[threading.Event] = None,
        *,
        preview_max_size: Optional[int] = None,
    ) -> None:
        self._tool_path: Optional[Path] = None
        self._preview_max_size = (
            preview_max_size
            if preview_max_size is not None
            else SafetyLimits().preview_max_size
        )
        self._tool_source: Optional[str] = None
        self._current_process: Optional[subprocess.Popen[str]] = None
        self._process_lock = threading.Lock()
        self._cancel_event = cancel_event or threading.Event()

    @staticmethod
    def _is_frozen() -> bool:
        return bool(getattr(sys, "frozen", False))

    def _bundled_dir(self) -> Optional[Path]:
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / "bundled"
        try:
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

    def _verify_bundled_tool(self, executable: Path) -> None:
        if self._sha256(executable).lower() != SEVENZIP_EXE_SHA256:
            raise ExternalToolNotFoundError(
                "7z",
                "同梱7-Zipの整合性検証に失敗しました。kaitoを再インストールしてください。",
            )
        library = executable.with_name("7z.dll")
        if (
            not library.is_file()
            or self._sha256(library).lower() != SEVENZIP_DLL_SHA256
        ):
            raise ExternalToolNotFoundError(
                "7z.dll",
                "同梱7-Zip DLLの整合性検証に失敗しました。kaitoを再インストールしてください。",
            )

    def _find_tool(self) -> Path:
        if self._tool_path is not None and self._tool_path.is_file():
            if self._tool_source == "bundled":
                self._verify_bundled_tool(self._tool_path)
            return self._tool_path

        bundled_dir = self._bundled_dir()
        bundled = bundled_dir / self._BUNDLED_NAME if bundled_dir else None
        if bundled is not None and bundled.is_file():
            self._verify_bundled_tool(bundled)
            self._tool_path = bundled
            self._tool_source = "bundled"
            return bundled

        if self._is_frozen():
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
        executable = self._find_tool()
        actual_hash = self._sha256(executable)
        result = self._run_7z(["i"], timeout=10)
        version = "unknown"
        for line in result.stdout.splitlines():
            if "7-Zip" not in line:
                continue
            for token in line.split():
                if token[:1].isdigit() and "." in token:
                    version = token
                    break
            if version != "unknown":
                break
        expected_hash = SEVENZIP_EXE_SHA256 if self._tool_source == "bundled" else None
        return {
            "available": True,
            "source": self._tool_source or "unknown",
            "path": str(executable),
            "version": version,
            "sha256": actual_hash,
            "expected_sha256": expected_hash,
            "integrity": (
                "ok"
                if expected_hash is None or actual_hash == expected_hash
                else "mismatch"
            ),
        }

    def supports_format(self, extension: str) -> bool:
        return extension.lower() in self.supported_extensions

    def supports_creation(self, extension: str) -> bool:
        return extension.lower() in {".7z", ".zip"}

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
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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
        """非対話で7-Zipを実行し、処理中もキャンセルを監視する。"""
        self._check_cancelled()
        command = [str(self._find_tool()), *args, "-y", "-sccUTF-8"]
        if password is not None:
            command.append(f"-p{password}")

        creation_flags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        )
        process: Optional[subprocess.Popen[str]] = None
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creation_flags,
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
                    stdout, stderr = process.communicate(
                        timeout=min(0.2, max(0.01, timeout - elapsed))
                    )
                    break
                except subprocess.TimeoutExpired:
                    continue

            return subprocess.CompletedProcess(
                args=redact_command(command),
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
        """`7z l -slt`のKey = Valueブロックを安全側で解析する。"""
        entries: list[dict[str, str]] = []
        current: dict[str, str] = {}
        in_entries = False
        separator_found = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("---") and stripped.endswith("---"):
                separator_found = True
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
        if not separator_found:
            raise ExtractionFailedError(
                "7-Zip一覧出力にエントリ区切りがありません。出力形式が変更された可能性があります"
            )
        if current:
            entries.append(current)
        return entries

    def _entry_from_slt(self, data: dict[str, str]) -> Optional[ArchiveEntry]:
        entry_path = data.get("Path")
        if not entry_path:
            return None
        try:
            size = int(data.get("Size", "0").strip() or "0")
            packed_size = int(data.get("Packed Size", "0").strip() or "0")
        except ValueError as exc:
            raise ExtractionFailedError(f"不正なサイズ情報です: {entry_path}") from exc

        modified = datetime(1970, 1, 1)
        modified_text = data.get("Modified", "")
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                modified = datetime.strptime(modified_text, pattern)
                break
            except ValueError:
                continue

        link_target = data.get("Symbolic Link") or data.get("Hard Link")
        attributes = data.get("Attributes", "").lower()
        is_link = (
            bool(link_target) or "lrwx" in attributes or data.get("Reparse", "-") == "+"
        )
        return ArchiveEntry(
            name=entry_path.replace("\\", "/"),
            size=size,
            compressed_size=packed_size,
            modified=modified,
            is_dir=data.get("Folder", "-") == "+",
            is_encrypted=data.get("Encrypted", "-") == "+",
            is_link=is_link,
            link_target=link_target,
        )

    @staticmethod
    def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
        return f"{result.stderr}\n{result.stdout}".strip()

    def _raise_archive_error(
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
        if (
            "cannot open the file as archive" in combined
            or "is not archive" in combined
        ):
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
            self._raise_archive_error(path, password, result)

        raw_entries = self._parse_slt_output(result.stdout)
        entries = [
            entry
            for raw_entry in raw_entries
            if (entry := self._entry_from_slt(raw_entry)) is not None
        ]
        if not entries and raw_entries:
            raise ExtractionFailedError(
                "アーカイブ一覧の解析に失敗しました", archive_path=str(path)
            )
        return ArchiveInfo(
            path=path,
            entries=entries,
            is_encrypted=any(entry.is_encrypted for entry in entries),
            format_name=path.suffix.lower().lstrip("."),
        )

    def extract(self, path: Path, options: ExtractionOptions) -> None:
        self._check_cancelled()
        info = self.list_archive(path, password=options.password)
        selected = info.entries
        if options.members is not None:
            wanted = set(options.members)
            selected = [entry for entry in info.entries if entry.name in wanted]
            if len(selected) != len(wanted):
                missing = sorted(wanted - {entry.name for entry in selected})
                raise ExtractionFailedError(
                    f"指定されたエントリが見つかりません: {', '.join(missing)}"
                )
        check_archive_safety(selected, options)

        with tempfile.TemporaryDirectory(prefix="kaito_extract_") as temporary:
            staging = Path(temporary)
            arguments = ["x", str(path), f"-o{staging}"]
            if options.members:
                arguments.extend(options.members)
            timeout = min(
                3600.0,
                max(60.0, options.max_total_size / (10 * 1024 * 1024)),
            )
            result = self._run_7z(arguments, password=options.password, timeout=timeout)
            if result.returncode != 0:
                self._raise_archive_error(path, options.password, result)
            self._check_cancelled()
            validate_staging_tree(staging, options)
            merge_staging_tree(staging, options.dest_dir)

        if options.on_progress and selected:
            options.on_progress(len(selected), len(selected), path.name)

    @staticmethod
    def _validate_sources(sources: list[Path]) -> None:
        for source in sources:
            candidates = [source]
            if source.is_dir():
                candidates.extend(source.rglob("*"))
            for candidate in candidates:
                if is_reparse_or_link(candidate):
                    raise CompressionFailedError(
                        f"リンクまたはreparse pointは圧縮できません: {candidate}"
                    )

    def create(self, options: CompressionOptions) -> None:
        self._check_cancelled()
        extension = options.output_path.suffix.lower()
        if not self.supports_creation(extension):
            raise CompressionFailedError(
                f"{extension}形式の作成はサポートされていません",
                archive_path=str(options.output_path),
            )

        output = options.output_path.resolve(strict=False)
        for source in options.sources:
            resolved = source.resolve(strict=False)
            if resolved == output or (
                resolved.is_dir() and output.is_relative_to(resolved)
            ):
                raise CompressionFailedError(
                    "出力アーカイブが圧縮対象に含まれています",
                    archive_path=str(options.output_path),
                )
        self._validate_sources(options.sources)

        output.parent.mkdir(parents=True, exist_ok=True)
        level = max(0, min(9, options.compression_level))
        seven_zip_level = {
            0: 0,
            1: 1,
            2: 3,
            3: 3,
            4: 5,
            5: 5,
            6: 5,
            7: 7,
            8: 7,
            9: 9,
        }[level]

        with tempfile.TemporaryDirectory(
            prefix=".kaito_7z_", dir=output.parent
        ) as temporary:
            temporary_output = Path(temporary) / output.name
            arguments = ["a", f"-mx={seven_zip_level}"]
            if extension == ".zip":
                arguments.extend(
                    ["-tzip", "-mem=AES256"] if options.password else ["-tzip"]
                )
            elif options.password:
                arguments.append("-mhe=on")
            arguments.append(str(temporary_output))
            arguments.extend(str(source) for source in options.sources)
            result = self._run_7z(arguments, password=options.password)
            if result.returncode != 0:
                raise CompressionFailedError(
                    f"7z作成に失敗しました (exit {result.returncode})",
                    archive_path=str(options.output_path),
                )
            self._check_cancelled()
            verification = self._run_7z(
                ["t", str(temporary_output)],
                password=options.password,
                timeout=300,
            )
            if verification.returncode != 0:
                raise CompressionFailedError(
                    "作成したアーカイブの検証に失敗しました",
                    archive_path=str(options.output_path),
                )
            os.replace(temporary_output, output)

    def test_archive(
        self, path: Path, password: Optional[str] = None
    ) -> IntegrityCheckResult:
        """Run the 7-Zip test command without writing extracted files."""
        self._check_cancelled()
        info = self.list_archive(path, password=password)
        result = self._run_7z(["t", str(path)], password=password, timeout=3600)
        if result.returncode != 0:
            self._raise_archive_error(path, password, result)
        checked = sum(1 for entry in info.entries if entry.is_file)
        return IntegrityCheckResult(
            status="passed",
            checked_entries=checked,
            message=f"整合性検査に成功しました（{checked}ファイル、データエラーなし）",
        )

    def read_entry(
        self,
        path: Path,
        entry_name: str,
        password: Optional[str] = None,
    ) -> Optional[bytes]:
        self._check_cancelled()
        info = self.list_archive(path, password=password)
        entry = next((item for item in info.entries if item.name == entry_name), None)
        if (
            entry is None
            or entry.is_dir
            or entry.is_link
            or entry.size > self._preview_max_size
        ):
            return None

        with tempfile.TemporaryDirectory(prefix="kaito_preview_") as temporary:
            staging = Path(temporary)
            result = self._run_7z(
                ["x", str(path), f"-o{staging}", entry_name, "-aos"],
                password=password,
            )
            if result.returncode != 0:
                return None
            target = validate_entry_path(entry_name, staging)
            if not target.is_file() or is_reparse_or_link(target):
                return None
            if target.stat().st_size > self._preview_max_size:
                return None
            return target.read_bytes()
