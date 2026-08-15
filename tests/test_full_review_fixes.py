from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

import kaito.archive.zip_backend as zip_backend_module
from kaito.archive.service import ArchiveService
from kaito.diagnostics import _sanitize_error
from kaito.domain.errors import CompressionFailedError
from kaito.domain.models import CompressionOptions


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


def test_test_suite_does_not_spawn_bundled_7z() -> None:
    """テスト実行時に bundled/7z.exe を subprocess で起動しない (回帰ガード)。

    コンソール窓のポップアップ防止と外部依存ゼロのため、テストコードから
    7z.exe を起動してはならない。アーカイブフィクスチャは
    tests/fixtures/archive/ の uuencode 済み固定バイナリからデコードする。
    """
    conftest = Path("tests/conftest.py").read_text(encoding="utf-8")
    assert "_run_7z" not in conftest
    assert "subprocess" not in conftest

    dll_poc = Path("tests/test_dll_poc.py").read_text(encoding="utf-8")
    assert "bundled/7z.exe" not in dll_poc
    assert "_create_encrypted_zip" not in dll_poc
    assert "_create_encrypted_7z" not in dll_poc

    encrypted_zip = Path("tests/test_encrypted_zip.py").read_text(encoding="utf-8")
    assert "subprocess" not in encrypted_zip
    assert "_create_aes_zip" not in encrypted_zip
