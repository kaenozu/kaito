"""Archive inspection, integrity result, filtering, and selection helpers."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Literal

from kaito.archive.safety import check_archive_safety
from kaito.domain.errors import ArchiveBombError, UnsafeArchiveError
from kaito.domain.models import (
    ArchiveEntry,
    ArchiveInfo,
    ExtractionOptions,
    SafetyLimits,
)

SafetyStatus = Literal["safe", "warning", "blocked"]
IntegrityStatus = Literal["passed", "failed"]

_EXECUTABLE_EXTENSIONS = {
    ".bat",
    ".cmd",
    ".com",
    ".cpl",
    ".dll",
    ".exe",
    ".hta",
    ".js",
    ".jse",
    ".lnk",
    ".msi",
    ".msp",
    ".ps1",
    ".reg",
    ".scr",
    ".vbe",
    ".vbs",
    ".wsf",
}
_IMAGE_EXTENSIONS = {".bmp", ".gif", ".ico", ".jpeg", ".jpg", ".png", ".webp"}
_DOCUMENT_EXTENSIONS = {
    ".csv",
    ".doc",
    ".docx",
    ".epub",
    ".html",
    ".md",
    ".odt",
    ".pdf",
    ".ppt",
    ".pptx",
    ".rtf",
    ".txt",
    ".xls",
    ".xlsx",
}
_ARCHIVE_EXTENSIONS = {".7z", ".gz", ".rar", ".tar", ".tgz", ".zip"}


@dataclass(frozen=True)
class SafetyFinding:
    """One human-readable safety observation."""

    severity: Literal["info", "warning", "blocked"]
    code: str
    message: str
    entry_name: str | None = None


@dataclass(frozen=True)
class ArchiveSafetyReport:
    """A non-destructive safety report for an archive listing."""

    status: SafetyStatus
    findings: tuple[SafetyFinding, ...]
    entry_count: int
    file_count: int
    encrypted_count: int
    executable_count: int
    total_size: int
    compressed_size: int
    compression_ratio: float

    @property
    def can_extract(self) -> bool:
        return self.status != "blocked"

    @property
    def summary(self) -> str:
        if self.status == "blocked":
            return "危険な項目を検出"
        if self.status == "warning":
            return "注意事項あり"
        return "問題なし"

    def format_text(self) -> str:
        lines = [
            f"判定: {self.summary}",
            f"エントリ: {self.entry_count}",
            f"ファイル: {self.file_count}",
            f"展開後サイズ: {_format_size(self.total_size)}",
            f"圧縮率: {self.compression_ratio:.1f}x",
            f"暗号化ファイル: {self.encrypted_count}",
            f"実行可能・スクリプト: {self.executable_count}",
            "",
            "検査結果:",
        ]
        if not self.findings:
            lines.append("- 危険なパス、リンク、上限超過は見つかりませんでした")
        else:
            for finding in self.findings:
                prefix = {"info": "INFO", "warning": "注意", "blocked": "拒否"}[
                    finding.severity
                ]
                suffix = f" ({finding.entry_name})" if finding.entry_name else ""
                lines.append(f"- [{prefix}] {finding.message}{suffix}")
        return "\n".join(lines)


@dataclass(frozen=True)
class IntegrityCheckResult:
    """Result of testing all readable archive data without extracting it."""

    status: IntegrityStatus
    checked_entries: int
    message: str

    @property
    def passed(self) -> bool:
        return self.status == "passed"


def inspect_archive(info: ArchiveInfo, limits: SafetyLimits) -> ArchiveSafetyReport:
    """Inspect an archive listing without writing extracted files."""
    findings: list[SafetyFinding] = []
    blocked = False

    options = ExtractionOptions(
        dest_dir=Path.cwd() / ".kaito-inspection",
        max_total_size=limits.max_total_size,
        max_file_size=limits.max_single_file_size,
        max_entries=limits.max_entries,
        max_compression_ratio=limits.max_compression_ratio,
        max_path_length=limits.max_path_length,
    )
    try:
        check_archive_safety(info.entries, options)
    except (ArchiveBombError, UnsafeArchiveError) as exc:
        blocked = True
        findings.append(SafetyFinding("blocked", "safety-gate", str(exc)))

    files = [entry for entry in info.entries if entry.is_file]
    encrypted = [entry for entry in files if entry.is_encrypted]
    executables = [
        entry
        for entry in files
        if Path(entry.name).suffix.lower() in _EXECUTABLE_EXTENSIONS
    ]
    links = [entry for entry in info.entries if entry.is_link]
    total_size = sum(max(0, entry.size) for entry in files)
    compressed_size = sum(max(0, entry.compressed_size) for entry in files)
    ratio = (
        total_size / compressed_size
        if compressed_size
        else (1.0 if total_size == 0 else float("inf"))
    )

    if encrypted:
        findings.append(
            SafetyFinding(
                "info",
                "encrypted",
                f"暗号化ファイルが{len(encrypted)}件あります",
            )
        )
    if executables:
        findings.append(
            SafetyFinding(
                "warning",
                "executables",
                f"実行可能ファイルまたはスクリプトが{len(executables)}件あります",
            )
        )
    if links and not blocked:
        blocked = True
        findings.append(
            SafetyFinding("blocked", "links", f"リンクエントリが{len(links)}件あります")
        )

    if (
        total_size >= int(limits.max_total_size * 0.8)
        and total_size <= limits.max_total_size
    ):
        findings.append(
            SafetyFinding(
                "warning",
                "near-total-limit",
                "展開後サイズが安全上限の80%を超えています",
            )
        )
    if (
        ratio != float("inf")
        and ratio >= limits.max_compression_ratio * 0.8
        and ratio <= limits.max_compression_ratio
    ):
        findings.append(
            SafetyFinding(
                "warning",
                "near-ratio-limit",
                "圧縮率が安全上限の80%を超えています",
            )
        )

    for entry in files:
        lower_name = entry.name.lower()
        suffixes = Path(lower_name).suffixes
        if len(suffixes) >= 2 and suffixes[-1] in _EXECUTABLE_EXTENSIONS:
            apparent = suffixes[-2]
            if apparent in _IMAGE_EXTENSIONS | _DOCUMENT_EXTENSIONS:
                findings.append(
                    SafetyFinding(
                        "warning",
                        "double-extension",
                        "二重拡張子で実行ファイルを偽装している可能性があります",
                        entry.name,
                    )
                )

    status: SafetyStatus
    if blocked:
        status = "blocked"
    elif any(item.severity == "warning" for item in findings):
        status = "warning"
    else:
        status = "safe"

    return ArchiveSafetyReport(
        status=status,
        findings=tuple(findings),
        entry_count=len(info.entries),
        file_count=len(files),
        encrypted_count=len(encrypted),
        executable_count=len(executables),
        total_size=total_size,
        compressed_size=compressed_size,
        compression_ratio=ratio,
    )


def filter_entries(
    entries: list[ArchiveEntry], query: str, category: str
) -> list[ArchiveEntry]:
    """Filter entries by a glob/substring query and a GUI category."""
    normalized_query = query.strip().casefold()
    wildcard = "*" in normalized_query or "?" in normalized_query

    def matches_query(entry: ArchiveEntry) -> bool:
        if not normalized_query:
            return True
        candidate = entry.name.casefold()
        return (
            fnmatch(candidate, normalized_query)
            if wildcard
            else normalized_query in candidate
        )

    def matches_category(entry: ArchiveEntry) -> bool:
        if category in {"", "すべて", "all"}:
            return True
        suffix = Path(entry.name).suffix.lower()
        if category in {"画像", "images"}:
            return suffix in _IMAGE_EXTENSIONS
        if category in {"文書", "documents"}:
            return suffix in _DOCUMENT_EXTENSIONS
        if category in {"アーカイブ", "archives"}:
            return suffix in _ARCHIVE_EXTENSIONS
        if category in {"実行ファイル", "executables"}:
            return suffix in _EXECUTABLE_EXTENSIONS
        if category in {"大きいファイル", "large"}:
            return entry.size >= 100 * 1024 * 1024
        if category in {"暗号化", "encrypted"}:
            return entry.is_encrypted
        return True

    return [
        entry for entry in entries if matches_query(entry) and matches_category(entry)
    ]


def expand_selected_members(
    entries: list[ArchiveEntry], selected_names: list[str]
) -> list[str]:
    """Expand selected directories to concrete member names for 7-Zip and ZIP."""
    if not selected_names:
        return []
    selected = set(selected_names)
    directories = {entry.name.rstrip("/") for entry in entries if entry.is_dir}
    prefixes = {
        name.rstrip("/") + "/"
        for name in selected_names
        if name.rstrip("/") in directories
    }
    result: list[str] = []
    for entry in entries:
        if entry.name in selected or any(
            entry.name.startswith(prefix) for prefix in prefixes
        ):
            result.append(entry.name)
    return result


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"
