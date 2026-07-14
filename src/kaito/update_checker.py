"""Small, fail-closed update checker for GitHub Releases."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

LATEST_RELEASE_API = "https://api.github.com/repos/kaenozu/kaito/releases/latest"
_UPDATE_ENDPOINT_ENV = "KAITO_UPDATE_ENDPOINT"
_GITHUB_TOKEN_ENV = "KAITO_GITHUB_TOKEN"
_VERSION_PATTERN = re.compile(
    r"^\s*v?(?P<release>\d+(?:\.\d+)*)(?P<suffix>[^+]*)?(?:\+.*)?$",
    re.IGNORECASE,
)
_PRERELEASE_PATTERN = re.compile(
    r"^[.-]?(?P<label>dev|a|alpha|b|beta|pre|preview|rc)"
    r"(?:[.-]?(?P<number>\d+))?",
    re.IGNORECASE,
)
_PRERELEASE_RANK = {
    "dev": 0,
    "a": 1,
    "alpha": 1,
    "b": 2,
    "beta": 2,
    "pre": 3,
    "preview": 3,
    "rc": 3,
}


@dataclass(frozen=True)
class UpdateCheckResult:
    """Result returned to the GUI without raising network errors."""

    checked: bool
    update_available: bool
    current_version: str
    latest_version: str | None = None
    release_url: str | None = None
    error: str | None = None


def _normalized_release(parts: tuple[int, ...]) -> tuple[int, ...]:
    normalized = list(parts)
    while len(normalized) > 1 and normalized[-1] == 0:
        normalized.pop()
    return tuple(normalized or [0])


def _version_key(version: str) -> tuple[tuple[int, ...], int, int, int]:
    """Return a conservative comparison key for stable and prerelease tags.

    Stable releases sort after prereleases with the same numeric release. Unknown
    suffixes are treated as prereleases so an unusual tag cannot incorrectly
    advertise itself as newer than the corresponding stable release.
    """
    match = _VERSION_PATTERN.fullmatch(version.strip())
    if match is None:
        return ((0,), 0, 0, 0)

    release = _normalized_release(
        tuple(int(part) for part in match.group("release").split("."))
    )
    suffix = (match.group("suffix") or "").strip()
    if not suffix:
        return (release, 1, 0, 0)

    prerelease = _PRERELEASE_PATTERN.match(suffix)
    if prerelease is None:
        return (release, 0, 0, 0)

    label = prerelease.group("label").lower()
    number_text = prerelease.group("number")
    return (
        release,
        0,
        _PRERELEASE_RANK[label],
        int(number_text) if number_text else 0,
    )


def _resolve_endpoint(endpoint: str | None) -> str:
    if endpoint is not None and endpoint.strip():
        return endpoint.strip()
    configured = os.environ.get(_UPDATE_ENDPOINT_ENV, "").strip()
    return configured or LATEST_RELEASE_API


def _resolve_token(token: str | None) -> str | None:
    if token is not None:
        stripped = token.strip()
        return stripped or None
    configured = os.environ.get(_GITHUB_TOKEN_ENV, "").strip()
    return configured or None


def check_for_update(
    current_version: str,
    *,
    endpoint: str | None = None,
    token: str | None = None,
    timeout: float = 5.0,
) -> UpdateCheckResult:
    """Check the latest stable release without making network failures fatal.

    A public release endpoint can be supplied through ``KAITO_UPDATE_ENDPOINT``.
    Private GitHub repositories require a runtime ``KAITO_GITHUB_TOKEN`` with
    read access; a token is never persisted by kaito.
    """
    resolved_endpoint = _resolve_endpoint(endpoint)
    resolved_token = _resolve_token(token)
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"kaito/{current_version}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if resolved_token:
        headers["Authorization"] = f"Bearer {resolved_token}"

    request = urllib.request.Request(resolved_endpoint, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload: Any = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if (
            exc.code in {403, 404}
            and resolved_endpoint == LATEST_RELEASE_API
            and resolved_token is None
        ):
            error = (
                "更新確認先が非公開です。公開リリース用エンドポイントを"
                "KAITO_UPDATE_ENDPOINTへ設定してください。"
            )
        else:
            error = f"HTTP {exc.code}: {exc.reason}"
        return UpdateCheckResult(
            checked=False,
            update_available=False,
            current_version=current_version,
            error=error,
        )
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
        update_available=_version_key(latest) > _version_key(current_version),
        current_version=current_version,
        latest_version=latest,
        release_url=url if isinstance(url, str) else None,
    )
