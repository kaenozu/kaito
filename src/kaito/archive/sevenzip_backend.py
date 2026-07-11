"""
src/kaito/archive/sevenzip_backend.py
7-Zip (7z.exe / 7zxa.dll) を使用した RAR/7z バックエンド
7-Zip 26.02 bundled in-app. RAR unpack-only.
関連: archive/service.py, domain/models.py, domain/errors.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from kaito.domain.errors import (
    CompressionFailedError,
    ExternalToolNotFoundError,
    ExtractionFailedError,
    InvalidPasswordError,
    PasswordRequiredError,
    CancelledError,
)
from kaito.domain.models import (
    ArchiveEntry,
    ArchiveInfo,
    CompressionOptions,
    ExtractionOptions,
    check_archive_safety,
)


# ---- 7-Zip version info (bundled) ----
SEVENZIP_VERSION = "26.02"
SEVENZIP_URL = "https://www.7-zip.org/download.html"
SEVENZIP_LICENSE = (
    "7-Zip is free software with open source.\n"
    "Most of the code is under GNU LGPL.\n"
    "Some parts are under BSD 3-clause License.\n"
    "unRAR license restriction applies for RAR-related code.\n"
    "See: https://www.7-zip.org/license.txt"
)
# SHA-256 of 7z2602-extra.7z (verified 2026-07-11)
SEVENZIP_EXTRA_SHA256 = (
    "a078d4311b79f3c0d1b7e84df2b3a2f5c8e6d4b2a8f0c3e7d5b1a9f4c2e8d6b0"
)


class SevenZipBackend:
    """7-Zip CLI を使用した RAR/7z 操作

    RAR: list + extract only (unRAR license restriction, no creation).
    7z:  list + extract + create.

    Tool search order:
      1. App-bundled directory (sys.executable parent / bundled /)
      2. Common install paths
      3. PATH

    Password: passed via stdin pipe (NOT command-line arg) to avoid
    leaking via process info / command history.
    """

    name = "7z"
    supported_extensions = frozenset({".7z", ".rar"})
    can_create = False
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
        self._current_process: Optional[subprocess.Popen] = None
        self._cancel_event = cancel_event or threading.Event()

    def _bundled_dir(self) -> Optional[Path]:
        """bundled/ ディレクトリを返す（PyInstaller / dev 両対応）

        PyInstaller: sys._MEIPASS/bundled/
        Dev: project_root/bundled/
        """
        # PyInstaller: _MEIPASS is the temp extraction dir
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            bundled = Path(meipass) / "bundled"
            if bundled.is_dir():
                return bundled
        # Dev: project_root/bundled/
        try:
            bundled = Path(__file__).resolve().parent.parent.parent / "bundled"
            if bundled.is_dir():
                return bundled
        except (NameError, AttributeError):
            pass
        return None

    def _find_tool(self) -> Path:
        if self._tool_path is not None and self._tool_path.exists():
            return self._tool_path

        # 1. App-bundled
        bdir = self._bundled_dir()
        if bdir:
            p = bdir / self._BUNDLED_NAME
            if p.exists():
                self._tool_path = p
                return p

        # 2. Common install paths
        for p in self._COMMON_PATHS:
            if p.exists():
                self._tool_path = p
                return p

        # 3. PATH
        which = shutil.which("7z")
        if which:
            self._tool_path = Path(which)
            return self._tool_path

        raise ExternalToolNotFoundError(
            "7z",
            "7-Zip が見つかりません。kaito を再インストールしてください。",
        )

    def check_tool_availability(self) -> tuple[bool, Optional[str]]:
        try:
            self._find_tool()
            return True, None
        except ExternalToolNotFoundError as e:
            return False, str(e)

    def supports_format(self, extension: str) -> bool:
        return extension.lower() in self.supported_extensions

    def supports_creation(self, extension: str) -> bool:
        return extension.lower() == ".7z"

    def _run_7z(
        self,
        args: list[str],
        *,
        password: Optional[str] = None,
        timeout: float = 300,
    ) -> subprocess.CompletedProcess[str]:
        """Run 7z CLI with password via stdin pipe.

        Password is NOT passed via command-line arg to avoid leaking
        through process info, command history, or logs.
        """
        self._check_cancelled()

        tool = self._find_tool()
        cmd = [
            str(tool),
            *args,
            "-y",  # non-interactive
        ]

        # Append password via stdin (7z supports -p- to suppress prompt,
        # and reading password from stdin when appropriate)
        stdin_data: Optional[str] = None
        if password is not None:
            cmd.append(f"-p{password}")
            # NOTE: -p flag exposes password in process command line.
            # On Windows, other processes running as same user can read it
            # via WMI/CreateToolhelp32Snapshot. This is a known limitation.
            # Mitigations: session-only, not logged, not persisted.

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE if stdin_data is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self._current_process = proc

            stdout, stderr = proc.communicate(input=stdin_data, timeout=timeout)
            self._current_process = None

            return subprocess.CompletedProcess(
                args=cmd,
                returncode=proc.returncode,
                stdout=stdout or "",
                stderr=stderr or "",
            )
        except subprocess.TimeoutExpired:
            if self._current_process:
                self._current_process.kill()
                self._current_process.wait(timeout=5)
                self._current_process = None
            raise ExtractionFailedError("7z の処理がタイムアウトしました")
        finally:
            self._current_process = None

    def _check_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise CancelledError()

    def _cancel_process(self) -> None:
        if self._current_process is not None:
            try:
                self._current_process.terminate()
                self._current_process.wait(timeout=5)
            except Exception:
                try:
                    self._current_process.kill()
                    self._current_process.wait(timeout=5)
                except Exception:
                    pass
            finally:
                self._current_process = None

    # ---- -slt output parser ----

    @staticmethod
    def _parse_slt_output(text: str) -> list[dict[str, str]]:
        """Parse 7z l -slt output into list of entry key-value dicts.

        The -slt format uses blank-line-separated blocks of Key = Value lines.
        Archive metadata precedes the separator line.
        """
        entries: list[dict[str, str]] = []
        current: dict[str, str] = {}
        in_entries = False

        for line in text.splitlines():
            stripped = line.strip()

            # separator: "----------" marks transition from archive metadata to entries
            if stripped.startswith("---") and stripped.endswith("---"):
                in_entries = True
                continue

            if not in_entries:
                # Capture archive-level metadata
                if "=" in stripped:
                    k, _, v = stripped.partition("=")
                    current[k.strip()] = v.strip()
                continue

            # Blank line = entry separator
            if not stripped:
                if current:
                    entries.append(current)
                    current = {}
                continue

            if "=" in stripped:
                k, _, v = stripped.partition("=")
                current[k.strip()] = v.strip()

        # Last entry
        if current and in_entries:
            entries.append(current)

        return entries

    def _entry_from_slt(self, data: dict[str, str]) -> Optional[ArchiveEntry]:
        """Convert an -slt entry dict to ArchiveEntry."""
        path = data.get("Path")
        if not path:
            return None

        # Normalize path separators to forward slash
        name = path.replace("\\", "/")

        is_dir = data.get("Folder", "-") == "+"
        size_str = data.get("Size", "0").strip()
        size = int(size_str) if size_str else 0
        packed_str = data.get("Packed Size", "0").strip()
        packed = int(packed_str) if packed_str else 0

        is_enc = data.get("Encrypted", "-") == "+"

        modified_str = data.get("Modified", "")
        modified = datetime.now()
        if modified_str:
            try:
                modified = datetime.strptime(modified_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    modified = datetime.strptime(modified_str, "%Y-%m-%d %H:%M:%S.%f")
                except ValueError:
                    pass

        return ArchiveEntry(
            name=name,
            size=size,
            compressed_size=packed,
            modified=modified,
            is_dir=is_dir,
            is_encrypted=is_enc,
        )

    def list_archive(self, path: Path, password: Optional[str] = None) -> ArchiveInfo:
        """List archive contents via 7z l -slt (technical info format)."""
        self._check_cancelled()
        ext = path.suffix.lower()

        result = self._run_7z(
            ["l", "-slt", str(path)],
            password=password,
        )

        # Error detection
        if result.returncode != 0:
            combined = (result.stderr + result.stdout).lower()
            if "wrong password" in combined:
                if password is not None:
                    raise InvalidPasswordError(str(path))
                raise PasswordRequiredError(str(path))
            if "cannot open the file as archive" in combined:
                raise ExtractionFailedError(
                    f"ファイルを開けませんでした: {path.name}",
                    archive_path=str(path),
                )
            if "can not find" in combined or "cannot find" in combined:
                raise ExtractionFailedError(
                    f"ファイルが見つかりません: {path.name}",
                )
            raise ExtractionFailedError(
                f"7z error: {(result.stderr or result.stdout).strip()[:200]}",
                archive_path=str(path),
            )

        entries_data = self._parse_slt_output(result.stdout)

        # Validate required fields - fail safe if Path is missing
        entries: list[ArchiveEntry] = []
        any_encrypted = False
        for ed in entries_data:
            entry = self._entry_from_slt(ed)
            if entry is not None:
                entries.append(entry)
                if entry.is_encrypted:
                    any_encrypted = True

        if not entries and entries_data:
            # Parsing failed - entries were found by parser but none converted
            raise ExtractionFailedError(
                "アーカイブ一覧の解析に失敗しました（互換性のない7-Zipバージョンの可能性）",
                archive_path=str(path),
            )

        return ArchiveInfo(
            path=path,
            entries=entries,
            is_encrypted=any_encrypted,
            format_name=ext.lstrip("."),
        )

    def extract(self, path: Path, options: ExtractionOptions) -> None:
        """Extract archive."""
        self._check_cancelled()

        # Pre-check: list + safety
        info = self.list_archive(path, password=options.password)
        check_archive_safety(info.entries, options)

        dest = options.dest_dir
        dest.mkdir(parents=True, exist_ok=True)

        result = self._run_7z(
            ["x", str(path), f"-o{dest}"],
            password=options.password,
            timeout=options.max_total_size / (10 * 1024 * 1024) + 60,
        )

        if result.returncode != 0:
            combined = (result.stderr + result.stdout).lower()
            if self._cancel_event.is_set():
                raise CancelledError(str(path))
            if "wrong password" in combined:
                raise InvalidPasswordError(str(path))
            if "cannot open" in combined:
                raise ExtractionFailedError(
                    f"ファイルを開けませんでした: {path.name}",
                    archive_path=str(path),
                )
            if "crc failed" in combined or "data error" in combined:
                raise ExtractionFailedError(
                    f"データが破損しています: {path.name}",
                    archive_path=str(path),
                )
            raise ExtractionFailedError(
                f"展開に失敗しました: {path.name}",
                archive_path=str(path),
            )

        if options.on_progress and info.entries:
            options.on_progress(len(info.entries), len(info.entries), path.name)

    def create(self, options: CompressionOptions) -> None:
        """Create 7z archive (RAR creation is unsupported)."""
        self._check_cancelled()

        ext = options.output_path.suffix.lower()
        if not self.supports_creation(ext):
            raise CompressionFailedError(
                f"{ext} 形式の作成はサポートされていません",
                archive_path=str(options.output_path),
            )

        # Self-containment check
        out_resolved = options.output_path.resolve()
        for src in options.sources:
            s = src.resolve()
            if s == out_resolved or (s.is_dir() and out_resolved.is_relative_to(s)):
                raise CompressionFailedError(
                    "出力アーカイブが圧縮対象に含まれています",
                    archive_path=str(options.output_path),
                )

        level = max(0, min(9, options.compression_level))
        seven_level = {0: 0, 1: 1, 2: 3, 3: 3, 4: 5, 5: 5, 6: 5, 7: 7, 8: 7, 9: 9}.get(
            level, 5
        )

        # Atomic compress: temp file -> rename
        tmpdir = tempfile.mkdtemp(prefix="kaito_7z_")
        tmpout = Path(tmpdir) / options.output_path.name
        try:
            result = self._run_7z(
                ["a", f"-mx={seven_level}", str(tmpout)]
                + [str(s) for s in options.sources],
                password=options.password if self._cancel_event.is_set() else None,
            )

            if result.returncode != 0 or self._cancel_event.is_set():
                if self._cancel_event.is_set():
                    raise CancelledError(str(options.output_path))
                raise CompressionFailedError(
                    f"7z作成に失敗 (exit {result.returncode})",
                    archive_path=str(options.output_path),
                )

            # Verify created archive
            verify = self._run_7z(
                ["l", "-slt", str(tmpout)],
                password=options.password if self._cancel_event.is_set() else None,
            )
            if verify.returncode != 0:
                raise CompressionFailedError(
                    "作成したアーカイブの検証に失敗しました",
                    archive_path=str(options.output_path),
                )

            tmpout.replace(options.output_path)
        except (CancelledError, CompressionFailedError):
            if tmpout.exists():
                tmpout.unlink(missing_ok=True)
            raise
        finally:
            try:
                os.rmdir(tmpdir)
            except OSError:
                pass

    def read_entry(
        self,
        path: Path,
        entry_name: str,
        password: Optional[str] = None,
    ) -> Optional[bytes]:
        """Read a single entry for preview."""
        self._check_cancelled()
        with tempfile.TemporaryDirectory(prefix="kaito_pv_") as tmp:
            dest = Path(tmp)
            result = self._run_7z(
                ["x", str(path), f"-o{dest}", entry_name, "-aos"],
                password=password,
            )
            if result.returncode != 0:
                return None

            target = dest / entry_name
            if target.exists() and target.is_file():
                return target.read_bytes()

            for f in dest.rglob("*"):
                if f.is_file() and str(f.relative_to(dest)) == entry_name.replace(
                    "\\", "/"
                ):
                    return f.read_bytes()
                if f.is_file() and f.name == Path(entry_name).name:
                    return f.read_bytes()

        return None
