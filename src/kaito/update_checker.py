"""Small, fail-closed update checker for GitHub Releases."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

LATEST_RELEASE_API = "https://api.github.com/repos/kaenozu/kaito/releases/latest"


@dataclass(frozen=True)
class UpdateCheckResult:
    """Result returned to the GUI without raising network errors."""

    checked: bool
    update_available: bool
    current_version: str
    latest_version: str | None = None
    release_url: str | None = None
    error: str | None = None


def _version_tuple(version: str) -> tuple[int, ...]:
    cleaned = version.strip().lower().removeprefix("v")
    stable = cleaned.split("+", 1)[0].split("-", 1)[0]
    parts: list[int] = []
    for token in stable.split("."):
        digits = "".join(character for character in token if character.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts or [0])


def check_for_update(
    current_version: str,
    *,
    endpoint: str = LATEST_RELEASE_API,
    timeout: float = 5.0,
) -> UpdateCheckResult:
    """Check the latest stable release while treating every network failure as non-fatal."""
    request = urllib.request.Request(
        endpoint,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"kaito/{current_version}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload: Any = json.loads(response.read().decode("utf-8"))
    except (
        OSError,
        TimeoutError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        urllib.error.URLError,
    ) as exc:
        return UpdateCheckResult(
            checked=False,
            update_available=False,
            current_version=current_version,
            error=str(exc),
        )

    if not isinstance(payload, dict):
        return UpdateCheckResult(
            checked=False,
            update_available=False,
            current_version=current_version,
            error="GitHub Releases API returned an unexpected response",
        )

    tag = payload.get("tag_name")
    url = payload.get("html_url")
    if not isinstance(tag, str) or not tag.strip():
        return UpdateCheckResult(
            checked=False,
            update_available=False,
            current_version=current_version,
            error="Latest release did not contain a tag name",
        )

    latest = tag.removeprefix("v")
    return UpdateCheckResult(
        checked=True,
        update_available=_version_tuple(latest) > _version_tuple(current_version),
        current_version=current_version,
        latest_version=latest,
        release_url=url if isinstance(url, str) else None,
    )
