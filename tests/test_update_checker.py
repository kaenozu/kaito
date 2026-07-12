from __future__ import annotations

from typing import Any

from kaito.update_checker import check_for_update


class _Response:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def test_update_available(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response(
            b'{"tag_name":"v0.11.0","html_url":"https://example.invalid/release"}'
        ),
    )

    result = check_for_update("0.10.1")

    assert result.checked
    assert result.update_available
    assert result.latest_version == "0.11.0"


def test_latest_version_is_not_reported_as_update(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response(
            b'{"tag_name":"v0.10.1","html_url":"https://example.invalid/release"}'
        ),
    )

    result = check_for_update("0.10.1")

    assert result.checked
    assert not result.update_available


def test_network_failure_is_non_fatal(monkeypatch: Any) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise OSError("offline")

    monkeypatch.setattr("urllib.request.urlopen", fail)

    result = check_for_update("0.10.1")

    assert not result.checked
    assert not result.update_available
    assert result.error == "offline"
