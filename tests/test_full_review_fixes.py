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


def test_test_suite_spawns_bundled_7z_only_with_no_window() -> None:
    """テスト内の 7z.exe 起動は CREATE_NO_WINDOW 付きに限る (回帰ガード)。

    AES暗号化フィクスチャの作成は bundled/7z.exe に依存するため、
    「起動しない」から「コンソール窓を出さずに起動する」へ不変条件を更新する。
    読み取り系が subprocess を生まないことは test_zip_read_path_is_unified_on_7z_dll
    が別途検証する。
    """
    conftest = Path("tests/conftest.py").read_text(encoding="utf-8")
    assert "_run_7z" in conftest
    assert "CREATE_NO_WINDOW" in conftest

    unzip = Path("tests/test_unzip.py").read_text(encoding="utf-8")
    assert "CREATE_NO_WINDOW" in unzip

    encrypted_zip = Path("tests/test_encrypted_zip.py").read_text(encoding="utf-8")
    assert "subprocess" not in encrypted_zip
    assert "_create_aes_zip" not in encrypted_zip


def test_manual_acceptance_runner_chains_prepare_and_evidence() -> None:
    runner = Path("tools/run_manual_acceptance.ps1").read_text(encoding="utf-8")
    prepare = Path("tools/prepare_acceptance.ps1").read_text(encoding="utf-8")

    # ワンコマンドの手動受け入れセッション（prepare -> Before -> 起動 -> After）
    assert "prepare_acceptance.ps1" in runner
    assert "collect_acceptance_evidence.ps1" in runner
    assert "-Phase Before" in runner
    assert "-Phase After" in runner
    assert "GUI_ACCEPTANCE.md" in runner

    # テスト用パスワードは名前付き定数に集約（断片リテラルは定義の1箇所のみ）
    assert "EncryptedArchivePassword" in prepare
    assert "EncryptedRarPassword" in prepare
    assert prepare.count("Kaito-Acceptance-") == 1
    assert prepare.count("2026!") == 1
    assert prepare.count("12345678") == 1


def test_registry_inventory_is_single_source_of_truth() -> None:
    inv = json.loads(Path("tools/registry-inventory.json").read_text(encoding="utf-8"))
    installer_test = Path("tools/test_installer.ps1").read_text(encoding="utf-8")
    evidence = Path("tools/collect_acceptance_evidence.ps1").read_text(encoding="utf-8")
    context_menu = Path("src/kaito/context_menu.py").read_text(encoding="utf-8")
    iss = Path("installer/kaito.iss").read_text(encoding="utf-8")

    # 両検証スクリプトはレジストリ在庫を tools/registry-inventory.json から読む
    assert "registry-inventory.json" in installer_test
    assert "registry-inventory.json" in evidence

    # 在庫の値（拡張子・アクション名・AppId）を PS1 に直書きしない
    for literal in (
        ".zip",
        ".rar",
        ".7z",
        "kaito_extract",
        "kaito_test",
        "kaito_compress",
        "B8F4C3D2",
    ):
        assert literal not in installer_test
        assert literal not in evidence

    # ランタイム（context_menu.py）の登録定義と一致
    for extension in inv["extensions"]:
        assert f'"{extension}"' in context_menu
    for action in (inv["extract_action"], inv["test_action"], inv["compress_action"]):
        assert action in context_menu
    for label in inv["labels"].values():
        assert label in context_menu

    # インストーラーのアンインストール AppId と一致
    assert inv["app_id"] in iss


def test_extraction_options_defaults_derive_from_safety_limits() -> None:
    """ExtractionOptions の上限既定値は SafetyLimits から導出する（二重定義の構造的排除）。"""
    source = Path("src/kaito/domain/models.py").read_text(encoding="utf-8")

    # 上限の既定値は SafetyLimits から default_factory で導出する（折り返し整形に依存しない compact 比較）
    compact = "".join(source.split())
    assert "field(default_factory=lambda:SafetyLimits().max_total_size)" in compact
    assert (
        "field(default_factory=lambda:SafetyLimits().max_single_file_size)" in compact
    )
    assert "field(default_factory=lambda:SafetyLimits().max_entries)" in compact
    assert (
        "field(default_factory=lambda:SafetyLimits().max_compression_ratio)" in compact
    )
    assert "field(default_factory=lambda:SafetyLimits().max_path_length)" in compact

    # 上限のリテラル値は SafetyLimits に 1 回だけ定義する（ExtractionOptions に再掲しない）
    assert source.count("10 * 1024 * 1024 * 1024") == 1
    assert source.count("2 * 1024 * 1024 * 1024") == 1
    assert source.count("max_entries: int = 100000") == 1
    assert source.count("max_compression_ratio: float = 1000.0") == 1
    assert source.count("max_path_length: int = 260") == 1


def test_preview_limits_are_user_configurable() -> None:
    """プレビュー上限は設定スキーマ・GUI 配線・ダイアログの3層で設定可能にする。"""
    settings_src = Path("src/kaito/settings.py").read_text(encoding="utf-8")
    unzip_src = Path("src/kaito/gui/unzip_app.py").read_text(encoding="utf-8")
    dialog_src = Path("src/kaito/gui/settings_dialog.py").read_text(encoding="utf-8")

    # 設定スキーマの既定値は SafetyLimits から導出する（リテラルの二重定義なし）
    assert '"preview_max_size": SafetyLimits.preview_max_size' in settings_src
    assert (
        '"preview_max_image_pixels": SafetyLimits.preview_max_image_pixels'
        in settings_src
    )

    # GUI は設定値を SafetyLimits 構築に渡し、ダイアログに編集欄を持つ（ラベルは i18n キー）
    unzip_compact = "".join(unzip_src.split())
    assert 'self._settings.get("preview_max_size"' in unzip_compact
    assert 'self._settings.get("preview_max_image_pixels"' in unzip_compact
    assert 'tr("settings.preview")' in dialog_src


def test_zip_read_path_is_unified_on_7z_dll() -> None:
    """読み取り系は DllArchiveBackend (7z.dll) に統一され、zipfile は作成専用。

    ZIP の stdlib zipfile 読み取りパスが復活すると回帰を検出する。
    """
    service = Path("src/kaito/archive/service.py").read_text(encoding="utf-8")
    zip_backend = Path("src/kaito/archive/zip_backend.py").read_text(encoding="utf-8")
    dll_backend = Path("src/kaito/archive/dll_backend.py").read_text(encoding="utf-8")

    # 読み取り系は DllArchiveBackend にルーティングされる
    assert "self._dll_backend.list_archive" in service
    assert "self._dll_backend.read_entry" in service
    assert "self._dll_backend.extract" in service
    assert "self._dll_backend.test_archive" in service
    assert "_encrypted_zip_uses_sevenzip" not in service

    # 作成のみが既存バックエンド (zipfile / 7z CLI) に残る
    assert "self._zip_backend.create" in service
    assert "self._sevenzip_backend.create" in service
    assert "self._zip_backend.extract" not in service
    assert "self._sevenzip_backend.extract" not in service
    assert "self._sevenzip_backend.list_archive" not in service

    # zip_backend は作成専用 (読み取りメソッドを持たない)
    assert "def create" in zip_backend
    for method in ("def list_archive", "def read_entry", "def test_archive"):
        assert method not in zip_backend
    assert "def extract" not in zip_backend

    # DLL バックエンドはプロセスを生まない (読み取り時のパスワード露出ゼロ)
    assert "import subprocess" not in dll_backend
    assert "subprocess.Popen" not in dll_backend
    assert "subprocess.run" not in dll_backend
