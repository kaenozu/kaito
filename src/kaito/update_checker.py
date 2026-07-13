"""Small, fail-closed update checker for GitHub Releases."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

LATEST_RELEASE_API = "https://api.github.com/repos/kaenozu/kaito/releases/latest"
_UPDATE_ENDPOINT_ENV = "KAITO_UPDATE_ENDPOINT"
_GITHUB_TOKEN_ENV = "KAITO_GITHUB_TOKEN"


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
        update_available=_version_tuple(latest) > _version_tuple(current_version),
        current_version=current_version,
        latest_version=latest,
        release_url=url if isinstance(url, str) else None,
    )
