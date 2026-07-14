from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION = "0.12.0.dev0"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="\n")


pyproject = read("pyproject.toml")
pyproject = re.sub(r'(?m)^version = "[^"]+"$', f'version = "{VERSION}"', pyproject, count=1)
write("pyproject.toml", pyproject)

installer = read("installer/kaito.iss")
installer = re.sub(
    r"(?m)^; Override version:.*$",
    lambda _match: f"; Override version: ISCC.exe /DMyAppVersion={VERSION} installer\\kaito.iss",
    installer,
    count=1,
)
installer = re.sub(
    r'(?m)^  #define MyAppVersion "[^"]+"$',
    f'  #define MyAppVersion "{VERSION}"',
    installer,
    count=1,
)
write("installer/kaito.iss", installer)

version_test = read("tests/test_version.py")
version_test = re.sub(
    r'assert expected == "[^"]+"',
    f'assert expected == "{VERSION}"',
    version_test,
    count=1,
)
write("tests/test_version.py", version_test)

changelog = read("CHANGELOG.md")
marker = "## [0.11.0]"
if marker not in changelog:
    raise RuntimeError("CHANGELOG 0.11.0 marker not found")
history = marker + changelog.split(marker, 1)[1]
unreleased = """# Changelog

このプロジェクトの重要な変更を記録します。

形式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) を参考にし、バージョン番号は Semantic Versioning に従います。

## [Unreleased]

### Added

- Windows上でパッケージ済みGUIを起動し、実ウィンドウとスクリーンショットを確認する`GUI acceptance` workflow
- 選択した空フォルダーをZIP内へ保持する処理

### Changed

- コンソールスクリプトを診断CLIとExplorerガードを持つ`kaito.__main__:main`へ統一
- 更新確認先を実行時に差し替え可能にし、認証情報を設定ファイルへ保存しない構成へ変更
- CIで`uv lock --check`を必須化
- 個人利用向けの内部開発版として`0.12.0.dev0`を使用

### Fixed

- プレリリースのバージョン比較
- 展開パスワード入力のマスクと値の破棄
- 診断レポートにおけるパスワードと絶対パスの除外
- 安全診断で拒否した後に解凍操作が再有効化される問題
- 安全診断で拒否したアーカイブの選択解凍
- 最近のファイル履歴削除
- 7z／RARプレビューによるTkイベントスレッド停止
- 画像プレビューの画素数上限
- Windows reparse pointを含むZIP作成
- コンテキストメニュー実装の二重化

"""
write("CHANGELOG.md", unreleased + history)

readme = read("README.md")
readme = readme.replace(
    "- GitHub Releasesまたは公開更新エンドポイントによる更新通知（無効化可能）\n",
    "",
)
readme = readme.replace(
    "配布EXEは同梱した固定バージョンの7-Zipだけを使用します。",
    "ローカルで作成したEXEは同梱した固定バージョンの7-Zipだけを使用します。",
)
install_start = readme.index("## インストール")
operation_start = readme.index("## 基本操作")
local_install = """## ローカル利用

このアプリは個人利用を前提としており、公開Releaseや自動更新サービスは使用しません。

```powershell
uv lock --check
uv sync --frozen
uv run pyinstaller --clean --noconfirm build.spec
& "${env:ProgramFiles(x86)}\\Inno Setup 6\\ISCC.exe" installer\\kaito.iss
```

生成物は`dist/kaito.exe`と`dist/kaito-installer-*.exe`です。インストーラーは現在のユーザーだけにインストールし、管理者権限を必須としません。

"""
readme = readme[:install_start] + local_install + readme[operation_start:]
update_start = readme.index("## 更新確認")
gui_start = readme.index("## Windows GUI受け入れ")
readme = readme[:update_start] + readme[gui_start:]
write("README.md", readme)

gui_doc = """# Windows GUI check

This checklist complements automated tests for personal use. Run it when a change affects GUI behavior or Windows integration.

## Automated check

The `packaged-gui-smoke` job runs focused regressions, builds `kaito.exe`, starts the packaged GUI, requires a live top-level window, captures a screenshot, and uploads the executable and test output.

## Optional interaction checks

1. **Encrypted extraction password** — Confirm extraction-password fields are masked, cancel clears the value, and reopening does not restore it.
2. **Rapid preview switching** — Alternate quickly between text and image entries and confirm the UI remains responsive and stale results do not overwrite the latest selection.
3. **Blocked safety report** — Confirm full and selected extraction remain disabled after a blocked safety result.
4. **Recent-history deletion** — Delete recent history, restart kaito, and confirm entries do not return.
5. **Oversized image preview** — Confirm an oversized image is rejected without a hang or crash.
6. **Empty selected folder** — Create and extract a ZIP containing a completely empty selected root folder.
7. **Explorer integration** — Install the generated installer, verify context-menu commands, uninstall, and confirm registrations are removed.

Failures should be recorded with reproduction steps. These checks are quality checks for the owner, not public-release approval gates.
"""
write("docs/GUI_ACCEPTANCE.md", gui_doc)

full_review = read("tests/test_full_review_fixes.py")
pattern = re.compile(
    r"def test_release_and_ci_fail_closed_on_lock_and_signing\(\) -> None:\n.*?(?=\ndef test_gui_acceptance_workflow_builds_and_launches_packaged_gui)",
    re.S,
)
replacement = '''def test_personal_app_ci_uses_locked_build_and_installer_checks() -> None:\n    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")\n\n    assert 'branches: [master, "feature/**"]' in ci\n    assert '"agent/**"' not in ci\n    assert "uv lock --check" in ci\n    assert "pyinstaller --clean --noconfirm build.spec" in ci\n    assert "tools/test_installer.ps1" in ci\n    assert "gh release download" not in ci\n    assert "test_upgrade.ps1" not in ci\n\n'''
full_review, count = pattern.subn(replacement, full_review, count=1)
if count != 1:
    raise RuntimeError("release CI policy test block not found")
write("tests/test_full_review_fixes.py", full_review)

remove_paths = [
    "docs/PRODUCTION_SIGNING_AUTHORIZATION.md",
    "docs/RELEASE_CANDIDATE.md",
    "docs/RELEASE_OPERATIONS.md",
    "docs/RELEASE_PUBLICATION.md",
    "docs/RELEASE_SECURITY.md",
    "tests/test_generate_sbom.py",
    "tests/test_pr_approval_gate.py",
    "tests/test_production_signing_authorization.py",
    "tests/test_production_signing_workflow_policy.py",
    "tests/test_release_operations_policy.py",
    "tests/test_release_verifier_policy.py",
    "tests/test_release_workflow_policy.py",
    "tools/build_release_rehearsal.ps1",
    "tools/create_draft_release.ps1",
    "tools/generate_sbom.py",
    "tools/prepare_release.ps1",
    "tools/sign_windows.ps1",
    "tools/test_sign_windows.ps1",
    "tools/test_upgrade.ps1",
    "tools/test_verify_release_package.ps1",
    "tools/verify_pr_approval_gate.py",
    "tools/verify_production_signing_authorization.py",
    "tools/verify_release_package.ps1",
    "tools/verify_release_rehearsal.ps1",
]
for relative in remove_paths:
    (ROOT / relative).unlink(missing_ok=True)

ci = read(".github/workflows/ci.yml")
ci = ci.replace("timeout-minutes: 45", "timeout-minutes: 35", 1)
ci = ci.replace(
    "- name: Record release artifact checksums",
    "- name: Record build artifact checksums",
    1,
)
ci = ci.replace("artifacts/release-sha256.txt", "artifacts/build-sha256.txt")
start = ci.index("      - name: Download previous stable installer for upgrade E2E")
end = ci.index("      - name: Test install, registry integration, and uninstall")
ci = ci[:start] + ci[end:]
artifact_dir = ROOT / "artifacts/personal-app-workflows"
artifact_dir.mkdir(parents=True, exist_ok=True)
(artifact_dir / "ci.yml").write_text(ci, encoding="utf-8", newline="\n")

print("Prepared personal-app cleanup and simplified CI workflow.")
