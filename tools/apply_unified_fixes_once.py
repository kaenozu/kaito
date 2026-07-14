from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        raise RuntimeError(f"Expected text not found in {path}: {old[:80]!r}")
    write(path, text.replace(old, new, 1))


def insert_lock_check(path: str) -> None:
    text = read(path)
    if "uv python install 3.12" not in text:
        return
    pattern = re.compile(
        r"(?P<indent>^[ \t]*)- name: Set up Python 3\.12\n"
        r"(?P=indent)  run: uv python install 3\.12\n",
        re.MULTILINE,
    )

    def add_check(match: re.Match[str]) -> str:
        indent = match.group("indent")
        block = (
            f"{indent}- name: Verify lockfile is current\n"
            f"{indent}  run: uv lock --check\n"
        )
        following = text[match.end() : match.end() + len(block) + 2]
        return match.group(0) if "Verify lockfile is current" in following else match.group(0) + "\n" + block

    updated = pattern.sub(add_check, text)
    write(path, updated)


for workflow in (
    ".github/workflows/release.yml",
    ".github/workflows/release-hardening.yml",
    ".github/workflows/release-rehearsal.yml",
    ".github/workflows/release-draft-roundtrip.yml",
    ".github/workflows/production-signing-canary.yml",
):
    insert_lock_check(workflow)

replace_once(
    ".github/workflows/release.yml",
    "WINDOWS_SIGNING_MODE: ${{ vars.WINDOWS_SIGNING_MODE || 'disabled' }}",
    "WINDOWS_SIGNING_MODE: required",
)

signing = read("tools/sign_windows.ps1")
signing = signing.replace("$hasCertificate", "$certificateConfigured")
signing = signing.replace("$hasPassword", "$credentialConfigured")
write("tools/sign_windows.ps1", signing)

readme = read("README.md")
readme = readme.replace(
    "- GitHub Releasesの更新通知（無効化可能）",
    "- GitHub Releasesまたは公開更新エンドポイントによる更新通知（無効化可能）",
)
readme = readme.replace(
    "圧縮時は暗号化の有無を選べます。パスワードは確認入力付きのマスクされたダイアログで受け取り、永続保存しません。",
    "圧縮時は暗号化の有無を選べます。パスワードは確認入力付きのマスクされたダイアログで受け取り、永続保存しません。暗号化アーカイブの展開パスワードもマスクして入力します。",
)
readme = readme.replace(
    "# 取得と依存関係の同期\ngit clone https://github.com/kaenozu/kaito.git\ncd kaito\nuv sync --frozen",
    "# 取得とロックファイル検証・依存関係の同期\ngit clone https://github.com/kaenozu/kaito.git\ncd kaito\nuv lock --check\nuv sync --frozen",
)
readme = readme.replace(
    "起動時の更新確認はGitHub Releases APIへ短いHTTPSリクエストを送ります。ファイル名、アーカイブ内容、設定値は送信しません。設定画面から無効化でき、画面上の「更新確認」ボタンから手動実行もできます。",
    "更新確認は短いHTTPSリクエストでバージョン情報だけを取得します。ファイル名、アーカイブ内容、設定値、パスワードは送信しません。設定画面から無効化でき、画面上の「更新確認」ボタンから手動実行もできます。\n\n既定のGitHub Releases APIが非公開リポジトリを指す場合、認証なしでは更新情報を取得できません。配布時は次のどちらかを実行環境へ設定してください。値はkaitoの設定ファイルへ保存されません。\n\n- `KAITO_UPDATE_ENDPOINT`: 認証なしで取得できる公開Release API、または同じ`tag_name`／`html_url`形式を返すJSONエンドポイント\n- `KAITO_GITHUB_TOKEN`: 非公開GitHub Releasesを読むための最小権限トークン\n\nどちらも利用できない場合、更新確認だけを失敗として扱い、アーカイブ操作は継続します。安定版とプレリリースは分けて比較し、`1.2rc1`を`1.2.0`より新しいものとして誤通知しません。",
)
signing_section = """### Windowsコード署名

`tools/sign_windows.ps1`は、ローカル検証とRelease rehearsal向けに`disabled`、`optional`、`required`の3モードを提供します。

| 値 | 動作 |
|---|---|
| `disabled` | 署名情報を使用せず、未署名成果物を生成します。ローカル開発専用です。 |
| `optional` | 署名情報が両方未設定なら未署名で続行し、片側だけ設定または証明書不正なら失敗します。 |
| `required` | 有効な証明書と認証情報が揃わない限り、ビルド前に失敗します。 |

安定版のtag-triggered Release workflowは`required`へ固定されており、未署名のEXEまたはインストーラーを公開できません。Production Environmentには次を設定します。

- `WINDOWS_CERTIFICATE_BASE64`: PFXファイルのBase64
- `WINDOWS_CERTIFICATE_PASSWORD`: PFX認証情報
- `WINDOWS_TIMESTAMP_URL`: HTTPSのタイムスタンプサービスURL

署名前にBase64、PFX、秘密鍵、Code Signing EKU、有効期間、SignTool、タイムスタンプURLを検査します。署名後はSignToolとAuthenticode APIの両方で検証し、構成した証明書のthumbprintと一致しない成果物を拒否します。

Production EnvironmentのRequired Reviewerを利用できない場合は、[`docs/PRODUCTION_SIGNING_AUTHORIZATION.md`](docs/PRODUCTION_SIGNING_AUTHORIZATION.md)の一回限りの独立承認を使用します。成功したCIや自己承認は代替になりません。

"""
readme, count = re.subn(
    r"### Windowsコード署名\n.*?(?=### Release資産の検証)",
    signing_section,
    readme,
    count=1,
    flags=re.DOTALL,
)
if count != 1:
    raise RuntimeError("README signing section was not replaced")
readme = readme.replace(
    "## アーキテクチャ",
    "## Windows GUI受け入れ\n\n自動化された実ウィンドウ起動スモークと、手動確認の合格基準は[`docs/GUI_ACCEPTANCE.md`](docs/GUI_ACCEPTANCE.md)に記載しています。GUI関連PRでは`GUI acceptance` workflowが対象テスト、パッケージ作成、実ウィンドウ起動、スクリーンショット取得を実行します。\n\n## アーキテクチャ",
    1,
)
readme = readme.replace(
    "- コード署名証明書を設定しないビルドではSmartScreen警告が表示される場合があります",
    "- 非公開リポジトリからの更新確認には公開エンドポイントまたは読み取りトークンが必要です\n- ローカルの未署名ビルドではSmartScreen警告が表示される場合があります",
)
write("README.md", readme)

changelog = read("CHANGELOG.md")
unreleased = """## [Unreleased]

### Added

- Release資産へCycloneDX 1.6 runtime SBOMと、タグ・コミット・署名状態・資産ハッシュを記録する`RELEASE-METADATA.json`を追加
- 自己署名テスト証明書による署名統合テスト、非公開Release rehearsal、Draft Release再取得検証を追加
- 固定HEADのPR承認ゲート、Draft Release roundtrip canary、独立した一回限りのProduction署名承認を追加
- Windows GUIの対象テスト、パッケージ作成、実ウィンドウ起動、スクリーンショットを行う`GUI acceptance` workflowを追加

### Changed

- 安定版Release workflowの署名モードを`required`へ固定し、未署名成果物の公開を禁止
- Releaseを一旦Draftとして作成し、全資産を再ダウンロードしてSHA-256、メタデータ、SBOM、署名状態を照合した後に公開する方式へ変更
- コンソールスクリプトを診断CLIとExplorerガードを持つ`kaito.__main__:main`へ統一
- 更新確認先を`KAITO_UPDATE_ENDPOINT`で差し替え可能にし、非公開GitHub Releasesでは実行時の`KAITO_GITHUB_TOKEN`を使用可能に変更
- CIとRelease関連workflowで`uv lock --check`を必須化

### Fixed

- `pyproject.toml`と`uv.lock`でkaitoのバージョンが一致していなかった問題
- プレリリースの数字を連結し、`1.2rc1`を`1.21`相当として比較する可能性
- 暗号化アーカイブの展開パスワード入力がマスクされていなかった問題
- 診断レポートで分離形式のパスワード引数、`C:/`形式、空白を含む引用絶対パスを完全に除外できない問題
- 安全診断が拒否した後にGUI操作を挟むと解凍ボタンが再有効化される問題
- 安全診断が拒否したアーカイブで選択解凍を開始できる問題
- 最近のファイルメニューの「履歴を削除」が動作しない問題
- 7z／RARプレビューがTkイベントスレッドを停止させる問題
- 画像プレビューの画素数上限が適用されていなかった問題
- 完全に空の選択フォルダーをZIPへ保存できない問題
- ZIP作成時にWindows reparse pointを共通安全判定で拒否していなかった問題
- コンテキストメニュー登録・削除実装がGUIモジュールと専用モジュールへ二重化していた問題
- 公開済みReleaseの再実行で検証前に既存Assetを上書きできる問題
- 不正形式・重複・実体不一致の同梱チェックサムをSBOM生成が受理できる問題

### Security

- 署名PFXをBase64、認証情報、秘密鍵、Code Signing EKU、有効期間の順に検証し、一時PFXのACLを現在のWindowsユーザーだけへ制限
- 署名後にSignTool、Authenticode状態、構成済み証明書のthumbprint一致を検証
- Production署名承認を別のwrite権限保有者、固定`master` HEAD、nonce、30分以内の期限、単回消費へ束縛
- 巨大画像の画素数を完全デコード前に拒否し、PillowのDecompressionBomb警告を失敗として扱う

"""
changelog, count = re.subn(
    r"## \[Unreleased\]\n.*?(?=## \[0\.11\.0\])",
    unreleased,
    changelog,
    count=1,
    flags=re.DOTALL,
)
if count != 1:
    raise RuntimeError("CHANGELOG Unreleased section was not replaced")
write("CHANGELOG.md", changelog)

write(
    "docs/RELEASE_OPERATIONS.md",
    """# Release operations and approval gates

A green pull request does not by itself authorize a merge, tag, production-secret use, canary execution, or Release publication. Version-controlled safeguards, repository settings, independent approval, and explicit operational authorization remain separate controls.

## Repository protection gate

Protect `master` before merging the unified release and application hardening pull request.

Required branch protection or ruleset controls:

- require a pull request before merging;
- require at least one independent approving review;
- dismiss stale approvals after new commits;
- require approval of the most recent push by someone other than the pusher when supported;
- require all review conversations to be resolved;
- require `verify-windows`, `signing-and-sbom`, `build-rehearsal-package`, `verify-redownloaded-package`, and `packaged-gui-smoke`;
- require the pull request to be current with `master` when supported;
- prevent force pushes and branch deletion;
- apply the rule to administrators or prohibit administrative bypass for release-sensitive changes.

Do not substitute self-approval, a bot comment, a resolved thread, or successful CI for an independent approving review. Save screenshots or exported settings as administrative evidence.

## Unified pull-request process

The former stacked release PRs and application-fix PR are superseded by one clean `master`-based PR. It contains the final reviewed tree without importing the historical implementation commits that produced secret-scanner noise and ordering dependencies.

Before merge:

1. inspect the current PR diff against the live `master` tree;
2. confirm all required Actions jobs succeed on the exact current HEAD;
3. confirm zero unresolved review threads;
4. directly inspect and disposition any new GitGuardian incident against the clean PR;
5. complete the manual GUI checklist in `GUI_ACCEPTANCE.md` on the packaged artifact;
6. obtain an independent approving review anchored to the current HEAD;
7. revalidate the expected HEAD immediately before a separately authorized merge.

After this workflow file exists on `master`, run `Release PR approval gate` for later release-sensitive pull requests. The workflow is manual because `workflow_dispatch` can only be relied on after the workflow is present on the default branch.

## Production Environment

Configure a GitHub Environment named `production` before production signing:

- store `WINDOWS_CERTIFICATE_BASE64` and `WINDOWS_CERTIFICATE_PASSWORD` as Environment secrets;
- store `WINDOWS_TIMESTAMP_URL` as an HTTPS Environment variable;
- restrict deployment branches or tags to the intended release policy;
- verify ordinary pull-request workflows cannot read production secrets;
- add an independent Required Reviewer and prevent self-review when the plan supports those controls.

The stable Release workflow is fixed to required signing. Missing, partial, invalid, expired, incorrectly scoped, or mismatched signing material fails before publication.

If Environment Required Reviewers are unavailable, the one-time issue-comment authorization in `PRODUCTION_SIGNING_AUTHORIZATION.md` is mandatory. An unprotected Environment, a confirmation string alone, repository-owner self-approval, or CI success is not equivalent.

## Draft Release roundtrip canary

Run `Draft Release roundtrip canary` only from `master`, after required checks succeed and an operator is explicitly authorized to create and delete the temporary tag and Draft Release. It uploads the five expected assets, redownloads and verifies them, contains no publication command, and cleans up fail-closed.

## Production signing canary

Run `Production signing canary` only after Environment configuration, deployment restrictions, secret-scanner disposition, and independent authorization are verified. The approval binds repository, workflow, exact current `master` SHA, fresh nonce, expiration, and `APPROVE`; it is consumed once before the signing job accesses Environment secrets.

## Actual Release

A production Release is a separate decision. Authorization must identify the exact tag, commit, version, production certificate use, and publication action. The tag-triggered workflow validates current `master`, requires signing, creates a Draft Release, redownloads and verifies all assets through the shared production verifier, rechecks `master` and Release identity, and only then publishes. Any failure leaves the Release in draft state.
""",
)

security = read("docs/RELEASE_SECURITY.md")
security = security.replace(
    "The stable tag workflow is intentionally gated and fail-closed.",
    "The stable tag workflow is intentionally gated and fail-closed. Its signing mode is fixed to `required`; unsigned production assets cannot be published.",
)
write("docs/RELEASE_SECURITY.md", security)

write(
    "docs/GUI_ACCEPTANCE.md",
    """# Windows GUI acceptance

This checklist complements, but does not replace, automated tests. Perform it against the exact packaged artifact from the pull request's `GUI acceptance` workflow and record the workflow run, artifact SHA-256, Windows version, tester, and result.

## Automated gate

The `packaged-gui-smoke` job must pass on the exact PR HEAD. It runs focused regression tests, builds `kaito.exe`, starts the packaged GUI, requires a live top-level window, captures a screenshot, and uploads the executable, screenshot, and test output.

## Manual cases

1. **Encrypted extraction password** — Open an encrypted ZIP, RAR, and 7z. Confirm every extraction-password field displays mask characters, cancel clears the value, and reopening does not restore it.
2. **Rapid preview switching** — Alternate quickly between text and image entries in ZIP and 7z archives. Confirm the UI remains responsive and an older worker result never overwrites the latest selection.
3. **Blocked safety report** — Open an archive that exceeds a configured limit or contains a rejected path. Confirm both full extraction and selected extraction remain disabled after search, selection, preview, and settings interactions.
4. **Recent-history deletion** — Add at least two recent archives, choose `履歴を削除`, reopen the menu, and restart kaito. Confirm the entries do not return.
5. **Oversized image preview** — Open an archive containing an image above the configured pixel limit. Confirm a rejection message appears without a hang, crash, or full image rendering.
6. **Empty selected folder** — Create a ZIP from a completely empty selected folder, inspect the archive entry, extract it, and confirm the empty root directory is preserved.
7. **Explorer integration** — Install the generated installer, verify open/extract/integrity/compress context-menu commands, uninstall, and confirm registrations are removed.

## Pass rule

Every case must pass on the exact current PR HEAD. A changed commit invalidates the prior manual result. Record failures as issues with reproduction steps and do not mark the PR Ready for Review until they are corrected and retested.
""",
)

write(
    ".github/workflows/gui-acceptance.yml",
    """name: GUI acceptance

on:
  pull_request:
    branches: [master]
    paths:
      - ".github/workflows/gui-acceptance.yml"
      - "docs/GUI_ACCEPTANCE.md"
      - "pyproject.toml"
      - "uv.lock"
      - "build.spec"
      - "installer/**"
      - "src/kaito/archive/**"
      - "src/kaito/gui/**"
      - "src/kaito/diagnostics.py"
      - "src/kaito/update_checker.py"
      - "tests/test_full_review_fixes.py"
      - "tests/test_productivity_services.py"
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: gui-acceptance-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

jobs:
  packaged-gui-smoke:
    runs-on: windows-latest
    timeout-minutes: 35

    steps:
      - name: Check out repository
        uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2

      - name: Install uv
        uses: astral-sh/setup-uv@d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86 # v5

      - name: Set up Python 3.12
        run: uv python install 3.12

      - name: Verify lockfile is current
        run: uv lock --check

      - name: Install locked dependencies
        run: uv sync --frozen

      - name: Run focused GUI and safety regressions
        shell: pwsh
        run: |
          New-Item -ItemType Directory -Path artifacts -Force | Out-Null
          $output = & uv run --frozen pytest -q tests/test_full_review_fixes.py tests/test_productivity_services.py 2>&1
          $code = $LASTEXITCODE
          $output | Tee-Object -FilePath artifacts/gui-regressions.txt
          exit $code

      - name: Build packaged GUI
        run: uv run --frozen pyinstaller --clean --noconfirm build.spec

      - name: Launch real window and capture evidence
        shell: pwsh
        run: |
          Add-Type -AssemblyName System.Windows.Forms
          Add-Type -AssemblyName System.Drawing
          $exe = (Resolve-Path 'dist/kaito.exe').Path
          $process = Start-Process -FilePath $exe -PassThru
          try {
            $deadline = [DateTime]::UtcNow.AddSeconds(20)
            do {
              Start-Sleep -Milliseconds 500
              $process.Refresh()
              if ($process.HasExited) {
                throw "Packaged GUI exited before acceptance capture: $($process.ExitCode)"
              }
            } while ($process.MainWindowHandle -eq 0 -and [DateTime]::UtcNow -lt $deadline)
            if ($process.MainWindowHandle -eq 0) { throw 'Packaged GUI did not expose a top-level window.' }

            $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
            $bitmap = New-Object System.Drawing.Bitmap($bounds.Width, $bounds.Height)
            $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
            try {
              $graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
              $bitmap.Save((Join-Path (Resolve-Path artifacts).Path 'gui-startup.png'), [System.Drawing.Imaging.ImageFormat]::Png)
            }
            finally {
              $graphics.Dispose()
              $bitmap.Dispose()
            }
            "window_handle=$($process.MainWindowHandle)" | Set-Content artifacts/gui-window.txt -Encoding ascii
          }
          finally {
            if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
          }

      - name: Upload GUI acceptance package
        if: always()
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2
        with:
          name: kaito-gui-acceptance
          if-no-files-found: error
          path: |
            artifacts/
            dist/kaito.exe
            docs/GUI_ACCEPTANCE.md
""",
)

tests = read("tests/test_full_review_fixes.py")
replacement = """def test_release_and_ci_fail_closed_on_lock_and_signing() -> None:
    ci = Path(\".github/workflows/ci.yml\").read_text(encoding=\"utf-8\")
    release = Path(\".github/workflows/release.yml\").read_text(encoding=\"utf-8\")

    assert 'branches: [master, \"feature/**\"]' in ci
    assert '\"agent/**\"' not in ci
    assert \"uv lock --check\" in ci
    assert \"uv lock --check\" in release
    assert \"WINDOWS_SIGNING_MODE: required\" in release
    assert \"Validate Windows signing configuration\" in release
    assert \"Sign executable according to release mode\" in release
    assert \"Sign installer according to release mode\" in release
    assert \"Create draft GitHub Release with verified assets\" in release
    assert \"Verify redownloaded draft Release package\" in release
    assert \"Publish verified GitHub Release\" in release


def test_gui_acceptance_workflow_builds_and_launches_packaged_gui() -> None:
    workflow = Path(\".github/workflows/gui-acceptance.yml\").read_text(
        encoding=\"utf-8\"
    )
    checklist = Path(\"docs/GUI_ACCEPTANCE.md\").read_text(encoding=\"utf-8\")

    assert \"packaged-gui-smoke\" in workflow
    assert \"uv lock --check\" in workflow
    assert \"tests/test_full_review_fixes.py\" in workflow
    assert \"pyinstaller --clean --noconfirm build.spec\" in workflow
    assert \"MainWindowHandle\" in workflow
    assert \"gui-startup.png\" in workflow
    assert \"Rapid preview switching\" in checklist
    assert \"Empty selected folder\" in checklist


"""
tests, count = re.subn(
    r"def test_release_and_ci_fail_closed_on_lock_and_signing\(\) -> None:\n.*?(?=def test_console_script_routes_through_guarded_entrypoint)",
    replacement,
    tests,
    count=1,
    flags=re.DOTALL,
)
if count != 1:
    raise RuntimeError("Full-review workflow test was not replaced")
write("tests/test_full_review_fixes.py", tests)

operations_tests = read("tests/test_release_operations_policy.py")
operations_replacement = """def test_repository_protection_and_unified_merge_order_are_explicit() -> None:
    operations = _text(OPERATIONS_DOC_PATH)

    protection = operations.index(\"Protect `master` before merging\")
    merge_process = operations.index(\"Before merge:\")
    assert protection < merge_process
    assert \"Do not substitute self-approval\" in operations
    assert \"unified release and application hardening pull request\" in operations
    assert \"verify-windows\" in operations
    assert \"signing-and-sbom\" in operations
    assert \"build-rehearsal-package\" in operations
    assert \"verify-redownloaded-package\" in operations
    assert \"packaged-gui-smoke\" in operations
    assert \"workflow_dispatch\" in operations
    assert \"default branch\" in operations
    assert \"exact current HEAD\" in operations


"""
operations_tests, count = re.subn(
    r"def test_repository_protection_and_bootstrap_order_are_explicit\(\) -> None:\n.*?(?=def test_operational_workflows_use_distinct_concurrency_groups)",
    operations_replacement,
    operations_tests,
    count=1,
    flags=re.DOTALL,
)
if count != 1:
    raise RuntimeError("Release-operations policy test was not replaced")
write("tests/test_release_operations_policy.py", operations_tests)

release_policy = read("tests/test_release_workflow_policy.py")
if "test_release_workflow_requires_signed_production_artifacts" not in release_policy:
    release_policy += """


def test_release_workflow_requires_signed_production_artifacts() -> None:
    workflow = _workflow_text()

    assert \"WINDOWS_SIGNING_MODE: required\" in workflow
    assert \"Validate Windows signing configuration\" in workflow
    assert workflow.count(\"-Mode $env:WINDOWS_SIGNING_MODE\") == 3
    assert \"environment:\" in workflow
    assert \"name: production\" in workflow
"""
write("tests/test_release_workflow_policy.py", release_policy)

for temporary in (
    ROOT / ".github" / "workflows" / "unified-finalizer.yml",
    ROOT / "tools" / "apply_unified_fixes_once.py",
):
    temporary.unlink(missing_ok=True)
