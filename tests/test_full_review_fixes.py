from __future__ import annotations

import inspect
import io
import urllib.error
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PIL import Image

import kaito.archive.zip_backend as zip_backend_module
from kaito.archive.inspection import ArchiveSafetyReport
from kaito.archive.service import ArchiveService
from kaito.diagnostics import _sanitize_error
from kaito.domain.errors import CompressionFailedError
from kaito.domain.models import CompressionOptions, SafetyLimits
from kaito.gui.productivity import _ArchivePasswordDialog, ProductivityFeatures
from kaito.update_checker import LATEST_RELEASE_API, _version_key, check_for_update


class _Response:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def test_update_checker_uses_runtime_token_without_persisting_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str | None] = {}

    def fake_urlopen(request: object, *, timeout: float) -> _Response:
        captured["authorization"] = getattr(request, "get_header")("Authorization")
        captured["timeout"] = str(timeout)
        return _Response(
            b'{"tag_name":"v0.12.0","html_url":"https://example.invalid/release"}'
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = check_for_update("0.11.0", token="temporary-token", timeout=2.5)

    assert result.checked
    assert result.update_available
    assert captured == {
        "authorization": "Bearer temporary-token",
        "timeout": "2.5",
    }


def test_private_default_update_endpoint_has_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KAITO_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("KAITO_UPDATE_ENDPOINT", raising=False)

    def fail(*_args: object, **_kwargs: object) -> object:
        raise urllib.error.HTTPError(
            LATEST_RELEASE_API,
            404,
            "Not Found",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr("urllib.request.urlopen", fail)
    result = check_for_update("0.11.0")

    assert not result.checked
    assert not result.update_available
    assert result.error is not None
    assert "KAITO_UPDATE_ENDPOINT" in result.error


def test_update_version_ordering_handles_prereleases_and_trailing_zeroes() -> None:
    assert _version_key("1.2rc1") < _version_key("1.2.0")
    assert _version_key("1.2.0-rc.2") > _version_key("1.2.0-rc.1")
    assert _version_key("1.2") == _version_key("1.2.0")
    assert _version_key("1.2-unexpected") < _version_key("1.2")


def test_diagnostics_redact_split_passwords_and_forward_slash_paths() -> None:
    message = (
        "failed -p split-secret --password another-secret "
        "C:/Users/alice/private.zip /home/alice/private.zip remaining"
    )

    sanitized = _sanitize_error(message)

    assert "split-secret" not in sanitized
    assert "another-secret" not in sanitized
    assert "alice" not in sanitized
    assert sanitized.count("<path>") == 2
    assert "-p***" in sanitized
    assert "--password=***" in sanitized
    assert "remaining" in sanitized


def test_diagnostics_redact_complete_quoted_paths_with_spaces() -> None:
    message = (
        'failed "C:/Users/alice/My Private Archive.zip" and '
        "'//server/share/Customer Backup.zip' remaining"
    )

    sanitized = _sanitize_error(message)

    assert sanitized.count("<path>") == 2
    assert "alice" not in sanitized
    assert "Archive.zip" not in sanitized
    assert "server" not in sanitized
    assert "Backup.zip" not in sanitized
    assert "remaining" in sanitized


def test_zip_creation_preserves_an_empty_selected_root(tmp_path: Path) -> None:
    source = tmp_path / "empty-root"
    source.mkdir()
    archive = tmp_path / "empty.zip"

    ArchiveService().create(CompressionOptions(sources=[source], output_path=archive))

    with zipfile.ZipFile(archive) as handle:
        assert handle.namelist() == ["empty-root/"]


def test_zip_creation_rejects_reparse_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "junction"
    source.mkdir()
    archive = tmp_path / "output.zip"
    monkeypatch.setattr(
        zip_backend_module,
        "is_reparse_or_link",
        lambda path: path == source,
    )

    with pytest.raises(CompressionFailedError, match="reparse point"):
        ArchiveService().create(
            CompressionOptions(sources=[source], output_path=archive)
        )

    assert not archive.exists()


def _blocked_report() -> ArchiveSafetyReport:
    return ArchiveSafetyReport(
        status="blocked",
        findings=(),
        entry_count=1,
        file_count=1,
        encrypted_count=0,
        executable_count=0,
        total_size=1,
        compressed_size=1,
        compression_ratio=1.0,
    )


def test_safety_block_remains_applied_after_ui_reenable() -> None:
    features = ProductivityFeatures.__new__(ProductivityFeatures)
    features._safety_report = _blocked_report()
    features._selected_button = MagicMock()
    extract_button = MagicMock()
    features.app = SimpleNamespace(
        _extract_btn=extract_button,
        _current_archive_path=Path("sample.zip"),
        _entries=[object()],
    )

    features._apply_safety_controls(enabled=True)

    extract_button.configure.assert_called_once_with(state="disabled")
    features._selected_button.configure.assert_called_once_with(state="disabled")


def test_recent_history_delete_is_a_real_action() -> None:
    features = ProductivityFeatures.__new__(ProductivityFeatures)
    settings = MagicMock()
    status = MagicMock()
    refresh = MagicMock()
    mapping = {"sample.zip": "C:/sample.zip"}
    features.app = SimpleNamespace(
        _settings=settings,
        _recent_display_to_path=mapping,
        _refresh_recent_menu=refresh,
        _status_var=status,
    )
    features._original_recent_selected = MagicMock()

    features.on_recent_selected("履歴を削除")

    settings.set.assert_called_once_with("recent_files", [])
    assert mapping == {}
    refresh.assert_called_once_with()
    features._original_recent_selected.assert_not_called()


def test_archive_password_dialog_uses_a_masked_entry() -> None:
    source = inspect.getsource(_ArchivePasswordDialog.__init__)
    assert 'show="*"' in source


def test_image_preview_rejects_pixel_count_before_full_decode() -> None:
    image = Image.new("RGB", (20, 20))
    payload = io.BytesIO()
    image.save(payload, format="PNG")
    service = SimpleNamespace(
        safety_limits=SafetyLimits(preview_max_image_pixels=100),
        read_entry=lambda *_args, **_kwargs: payload.getvalue(),
    )
    features = ProductivityFeatures.__new__(ProductivityFeatures)
    features.app = SimpleNamespace(_archive_service=service)

    kind, message = features._load_preview(Path("sample.zip"), "large.png", None)

    assert kind == "message"
    assert "画素数" in str(message)


def test_release_and_ci_fail_closed_on_lock_and_signing() -> None:
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    release = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert 'branches: [master, "feature/**"]' in ci
    assert '"agent/**"' not in ci
    assert "uv lock --check" in ci
    assert "uv lock --check" in release
    assert release.count("-RequireSigning") == 2
    assert "Release executable is not validly signed" in release
    assert "Release installer is not validly signed" in release


def test_console_script_routes_through_guarded_entrypoint() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'kaito = "kaito.__main__:main"' in pyproject


def test_project_and_lock_versions_match() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    lockfile = Path("uv.lock").read_text(encoding="utf-8")
    project_version = pyproject.split('version = "', 1)[1].split('"', 1)[0]
    kaito_section = lockfile.split('name = "kaito"', 1)[1]
    locked_version = kaito_section.split('version = "', 1)[1].split('"', 1)[0]
    assert locked_version == project_version
