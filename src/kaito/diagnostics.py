"""Privacy-safe diagnostic report generation."""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path
from typing import Any

from kaito.archive.service import ArchiveService
from kaito.version import __version__


def build_diagnostic_report(
    service: ArchiveService,
    *,
    archive_path: Path | None = None,
    entry_count: int | None = None,
    encrypted: bool | None = None,
    last_error: str | None = None,
) -> str:
    """Build a report that intentionally excludes paths, entry names, and secrets."""
    backend: dict[str, Any]
    try:
        backend = service.backend_info()
    except Exception as exc:  # diagnostics must never crash the GUI
        backend = {"available": False, "error": type(exc).__name__}

    limits = service.safety_limits
    payload: dict[str, Any] = {
        "application": {
            "name": "kaito",
            "version": __version__,
            "frozen": bool(getattr(sys, "frozen", False)),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "backend": {
            "available": backend.get("available", False),
            "source": backend.get("source"),
            "version": backend.get("version"),
            "integrity": backend.get("integrity"),
            "sha256_matches_expected": (
                backend.get("sha256") == backend.get("expected_sha256")
                if backend.get("expected_sha256")
                else None
            ),
        },
        "safety_limits": {
            "max_entries": limits.max_entries,
            "max_total_size": limits.max_total_size,
            "max_single_file_size": limits.max_single_file_size,
            "max_compression_ratio": limits.max_compression_ratio,
            "max_path_length": limits.max_path_length,
        },
    }

    if archive_path is not None:
        payload["archive"] = {
            "extension": archive_path.suffix.lower(),
            "entry_count": entry_count,
            "encrypted": encrypted,
        }
    if last_error:
        payload["last_error"] = _sanitize_error(last_error)

    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _sanitize_error(message: str) -> str:
    """Avoid copying likely file paths or command-line secrets into reports."""
    pieces: list[str] = []
    for token in message.replace("\r", " ").replace("\n", " ").split():
        lower = token.lower()
        if lower.startswith("-p") and len(token) > 2:
            pieces.append("-p***")
        elif ":\\" in token or token.startswith("/") or token.startswith("\\\\"):
            pieces.append("<path>")
        else:
            pieces.append(token)
    return " ".join(pieces)[:1000]
