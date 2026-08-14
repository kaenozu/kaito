from __future__ import annotations

import inspect
import io
import json
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


def test_personal_app_ci_uses_locked_build_and_installer_checks() -> None:
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert 'branches: [master, "feature/**"]' in ci
    assert '"agent/**"' not in ci
    assert "uv lock --check" in ci
    assert "pyinstaller --clean --noconfirm build.spec" in ci
    assert "tools/test_installer.ps1" in ci
    assert "gh release download" not in ci
    assert "test_upgrade.ps1" not in ci


def test_gui_acceptance_workflow_builds_and_launches_packaged_gui() -> None:
    workflow = Path(".github/workflows/gui-acceptance.yml").read_text(encoding="utf-8")
    checklist = Path("docs/GUI_ACCEPTANCE.md").read_text(encoding="utf-8")

    assert "packaged-gui-smoke" in workflow
    assert "uv lock --check" in workflow
    assert "tests/test_full_review_fixes.py" in workflow
    assert "pyinstaller --clean --noconfirm build.spec" in workflow
    assert "MainWindowHandle" in workflow
    assert "gui-startup.png" in workflow
    assert "Rapid preview switching" in checklist
    assert "Empty selected folder" in checklist


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


def test_preview_size_limit_comes_from_safety_limits() -> None:
    source = Path("src/kaito/gui/unzip_app.py").read_text(encoding="utf-8")

    assert "_MAX_PREVIEW_FILE_SIZE" not in source
    assert "safety_limits.preview_max_size" in source


def test_7zip_pinned_definition_is_single_source_of_truth() -> None:
    pinned = json.loads(Path("bundled/7zip-pinned.json").read_text(encoding="utf-8"))
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    update = Path("tools/update_7zip.ps1").read_text(encoding="utf-8")
    backend = Path("src/kaito/archive/sevenzip_backend.py").read_text(encoding="utf-8")
    sums = Path("bundled/SHA256SUMS").read_text(encoding="utf-8")

    # ピン留め値（バージョン・URL・SHA-256）は JSON に一元化し、ci.yml / update_7zip.ps1 には直書きしない
    assert "bundled/7zip-pinned.json" in ci
    assert "bundled/7zip-pinned.json" in update
    assert pinned["package_sha256"] not in ci
    assert pinned["exe_sha256"] not in ci
    assert pinned["package_sha256"] not in update
    assert pinned["exe_sha256"] not in update

    # ランタイム整合性チェックの期待ハッシュ（frozen exe への焼き込み）は JSON と一致させる
    assert f'SEVENZIP_VERSION = "{pinned["version"]}"' in backend
    assert f'SEVENZIP_EXE_SHA256 = "{pinned["exe_sha256"]}"' in backend
    assert f'SEVENZIP_DLL_SHA256 = "{pinned["dll_sha256"]}"' in backend

    # 同梱チェックサム記録（SHA256SUMS）とも一致させる
    assert f"{pinned['exe_sha256']}  7z.exe" in sums
    assert f"{pinned['dll_sha256']}  7z.dll" in sums
