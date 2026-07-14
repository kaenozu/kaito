from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OLD_VERSION = "0.11.0"
NEW_VERSION = "0.12.0"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8", newline="\n")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one occurrence, found {count}")
    return text.replace(old, new, 1)


def update_version_files() -> None:
    pyproject = replace_once(
        read("pyproject.toml"),
        'version = "0.11.0"',
        'version = "0.12.0"',
        "pyproject version",
    )
    write("pyproject.toml", pyproject)

    installer = read("installer/kaito.iss")
    installer = installer.replace("/DMyAppVersion=0.11.0", "/DMyAppVersion=0.12.0")
    installer = replace_once(
        installer,
        '#define MyAppVersion "0.11.0"',
        '#define MyAppVersion "0.12.0"',
        "installer version",
    )
    write("installer/kaito.iss", installer)


def update_changelog() -> None:
    text = read("CHANGELOG.md")
    if "## [0.12.0]" in text:
        raise RuntimeError("CHANGELOG already contains 0.12.0")
    start = text.index("## [Unreleased]\n")
    body_start = start + len("## [Unreleased]\n")
    next_release = text.index("\n## [0.11.0]", body_start)
    body = text[body_start:next_release].strip()
    body = replace_once(
        body,
        "### Added\n\n",
        "### Added\n\n"
        "- 署名済みDraft Releaseの作成と、別承認で公開する二段階Release workflowを追加\n"
        "- `v0.11.0`から`v0.12.0`への上書き更新E2Eを追加\n",
        "CHANGELOG Added",
    )
    body = replace_once(
        body,
        "### Changed\n\n",
        "### Changed\n\n"
        "- タグpush workflowは検証済みDraft Releaseの作成までで停止し、公開は手動workflowへ分離\n"
        "- 公開workflowは元のbuild run、Release ID、tag、commit、再取得した資産を固定して再検証\n",
        "CHANGELOG Changed",
    )
    body = replace_once(
        body,
        "### Fixed\n\n",
        "### Fixed\n\n"
        "- 既存Draft Releaseを再利用して資産を上書きできる競合窓を排除\n",
        "CHANGELOG Fixed",
    )
    replacement = "## [Unreleased]\n\n## [0.12.0] - 2026-07-14\n\n" + body + "\n"
    write("CHANGELOG.md", text[:start] + replacement + text[next_release:])


def update_release_workflow() -> None:
    path = ".github/workflows/release.yml"
    text = read(path)
    text = replace_once(text, "name: Release", "name: Build signed draft Release", "workflow name")
    text = replace_once(
        text,
        "- name: Reject an existing public Release",
        "- name: Reject any existing Release",
        "early guard name",
    )
    text = replace_once(
        text,
        """          if ($null -ne $existing -and -not [bool]$existing.draft) {
            throw "Release $env:GITHUB_REF_NAME is already public. Refusing to overwrite public assets during a workflow re-run."
          }
""",
        """          if ($null -ne $existing) {
            throw "Release $env:GITHUB_REF_NAME already exists (id=$($existing.id), draft=$($existing.draft)). Refusing to reuse or overwrite any existing Release."
          }
""",
        "early existing Release guard",
    )
    text = replace_once(
        text,
        "- name: Reconfirm Release is absent or still draft before asset upload",
        "- name: Reconfirm Release is still absent before asset upload",
        "late guard name",
    )
    text = replace_once(
        text,
        """          if ($null -ne $existing -and -not [bool]$existing.draft) {
            throw "Release $env:GITHUB_REF_NAME became public before asset upload. Refusing to overwrite public assets."
          }
""",
        """          if ($null -ne $existing) {
            throw "Release $env:GITHUB_REF_NAME appeared before asset upload (id=$($existing.id), draft=$($existing.draft)). Refusing to reuse or overwrite it."
          }
""",
        "late existing Release guard",
    )

    old_create = text.index("      - name: Create draft GitHub Release with verified assets\n")
    confirm = text.index("      - name: Confirm Release remains draft before verification\n", old_create)
    new_create = """      - name: Create a new draft GitHub Release with verified assets
        id: draft_release
        shell: pwsh
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          $assets = @(
            'dist/kaito.exe',
            $env:KAITO_INSTALLER,
            'dist/kaito-sbom.cdx.json',
            'dist/RELEASE-METADATA.json',
            'dist/SHA256SUMS'
          )
          ./tools/create_draft_release.ps1 `
            -Tag $env:GITHUB_REF_NAME `
            -Commit $env:GITHUB_SHA `
            -Version $env:KAITO_VERSION `
            -AssetPaths $assets `
            -OutputPath $env:GITHUB_OUTPUT

"""
    text = text[:old_create] + new_create + text[confirm:]

    publish = text.index("      - name: Publish verified GitHub Release\n")
    tail = """      - name: Record verified draft release
        continue-on-error: true
        shell: pwsh
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          $metadata = Get-Content 'dist/RELEASE-METADATA.json' -Raw | ConvertFrom-Json
          $body = @\"
          ## v$env:KAITO_VERSION verified Draft Release ready

          Production-signed assets were uploaded to a newly created Draft Release, downloaded again, and verified. This workflow intentionally contains no publication command.

          Release ID: ``${{ steps.draft_release.outputs.id }}``
          Tag: ``$env:GITHUB_REF_NAME``
          Commit: ``$env:GITHUB_SHA``
          Build run ID: ``$env:GITHUB_RUN_ID``
          Signing result: ``$($metadata.signing.result)``

          Publication requires the separate ``Publish verified Release`` workflow with these exact identities.
          Draft Release: ${{ steps.draft_release.outputs.html_url }}
          Build workflow: $env:GITHUB_SERVER_URL/$env:GITHUB_REPOSITORY/actions/runs/$env:GITHUB_RUN_ID
          \"@
          gh issue comment 6 --repo $env:GITHUB_REPOSITORY --body $body

      - name: Record failed draft release workflow
        if: failure()
        continue-on-error: true
        shell: pwsh
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          $body = @\"
          ## v$env:KAITO_VERSION Draft Release workflow failed

          No Release was promoted to public. Existing Releases are never reused, existing public assets are never overwritten, and existing tags are never moved.

          Workflow: $env:GITHUB_SERVER_URL/$env:GITHUB_REPOSITORY/actions/runs/$env:GITHUB_RUN_ID
          \"@
          gh issue comment 6 --repo $env:GITHUB_REPOSITORY --body $body
"""
    write(path, text[:publish] + tail)


def update_ci() -> None:
    path = ".github/workflows/ci.yml"
    text = read(path)
    marker = """      - name: Test install, registry integration, and uninstall
        shell: pwsh
        run: ./tools/test_installer.ps1 -InstallerPath $env:KAITO_INSTALLER -ArtifactsDir artifacts
"""
    steps = """      - name: Download previous stable installer for upgrade E2E
        shell: pwsh
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          $root = Join-Path $env:RUNNER_TEMP 'kaito-previous-release'
          Remove-Item $root -Recurse -Force -ErrorAction SilentlyContinue
          New-Item -ItemType Directory -Path $root -Force | Out-Null
          gh release download 'v0.11.0' `
            --repo $env:GITHUB_REPOSITORY `
            --pattern 'kaito-installer-0.11.0.exe' `
            --dir $root
          if ($LASTEXITCODE -ne 0) { throw 'Unable to download v0.11.0 for upgrade E2E.' }
          $previous = @(Get-ChildItem $root -File -Filter 'kaito-installer-0.11.0.exe')
          if ($previous.Count -ne 1) { throw "Expected one previous installer, found $($previous.Count)" }
          "KAITO_PREVIOUS_INSTALLER=$($previous[0].FullName)" | Out-File $env:GITHUB_ENV -Append

      - name: Test in-place upgrade from v0.11.0
        shell: pwsh
        run: |
          ./tools/test_upgrade.ps1 `
            -PreviousInstallerPath $env:KAITO_PREVIOUS_INSTALLER `
            -CurrentInstallerPath $env:KAITO_INSTALLER `
            -ExpectedPreviousVersion '0.11.0' `
            -ExpectedCurrentVersion '0.12.0' `
            -ArtifactsDir artifacts

"""
    text = replace_once(text, marker, steps + marker, "CI installer step")
    write(path, text)


def update_docs() -> None:
    operations_path = "docs/RELEASE_OPERATIONS.md"
    operations = read(operations_path)
    old = """## Actual Release

A production Release is a separate decision. Authorization must identify the exact tag, commit, version, production certificate use, and publication action. The tag-triggered workflow validates current `master`, requires signing, creates a Draft Release, redownloads and verifies all assets through the shared production verifier, rechecks `master` and Release identity, and only then publishes. Any failure leaves the Release in draft state.
"""
    new = """## Actual Release

A production Release is a separate decision and is split into two operations.

1. After explicit tag authorization, push a new stable tag that points to the exact live `master` HEAD. `Build signed draft Release` requires production signing, refuses every existing Release for the tag, creates a new Draft Release, redownloads all five assets, and verifies them against build evidence.
2. Record the exact tag, commit, Release ID, and successful build run ID. Inspect the exact production-signed Draft artifacts.
3. After separate publication authorization, dispatch `Publish verified Release` from `master` with those exact identities and `PUBLISH_VERIFIED_RELEASE`.
4. The publication workflow downloads the original build-run evidence, redownloads the same Draft assets, runs the shared production verifier, rechecks live identity, and only then makes that Release public.

The build workflow contains no publication command. Existing Releases and tags are never reused, overwritten, or moved. See `RELEASE_PUBLICATION.md`.
"""
    write(operations_path, replace_once(operations, old, new, "operations release section"))

    security_path = "docs/RELEASE_SECURITY.md"
    security = read(security_path)
    old_security = """## Publication sequence

1. Validate the stable tag and current `master`.
2. Validate signing configuration and build the package.
3. Create or update a Draft Release only.
4. Download all Draft Release assets again.
5. Verify the downloaded package with the shared `production` profile.
6. Re-read the live `master` ref and Draft Release identity.
7. Publish only when every check still matches.

A failed verification leaves the Release in draft state. An already-public Release is rejected before build and again before asset upload.
"""
    new_security = """## Publication sequence

1. Validate the stable tag and current `master`.
2. Validate signing configuration and build the package.
3. Refuse every existing Release for the tag and create a brand-new Draft Release.
4. Upload exactly five assets to that new Release ID.
5. Download and verify all Draft assets with the shared `production` profile.
6. Stop with the Release in Draft state and record the exact Release ID and build run ID.
7. A separately dispatched workflow downloads the original build evidence and the same Draft assets, re-verifies them, and rechecks live master, tag, run, Release ID, Draft state, and asset count.
8. Publish only the exact verified Draft Release when every identity still matches.

Existing Draft or public Releases are never reused, and publication cannot occur in the tag-triggered build workflow.
"""
    write(security_path, replace_once(security, old_security, new_security, "security publication section"))


def main() -> None:
    update_version_files()
    update_changelog()
    update_release_workflow()
    update_ci()
    update_docs()


if __name__ == "__main__":
    main()
