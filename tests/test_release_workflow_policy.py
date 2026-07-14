from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_release_workflow_is_create_only_and_pins_release_id() -> None:
    workflow = _workflow_text()

    early_guard = workflow.index("- name: Require immutable create-only Release policy")
    build = workflow.index("- name: Build executable")
    create_guard = workflow.index(
        "- name: Reconfirm Release absence before create-only Draft creation"
    )
    create_release = workflow.index(
        "- name: Create a new Draft Release and upload assets by Release ID"
    )
    post_upload_guard = workflow.index(
        "- name: Confirm Release remains the same Draft before verification"
    )
    verification = workflow.index(
        "- name: Redownload and verify Draft Release assets by Release ID"
    )
    publication = workflow.index(
        "- name: Publish verified immutable GitHub Release by Release ID"
    )

    assert early_guard < build < create_guard < create_release
    assert create_release < post_upload_guard < verification < publication
    assert "RELEASE_IMMUTABILITY_ENABLED" in workflow
    assert "Release immutability must be enabled" in workflow
    assert "Invoke-RestMethod -Method Post -Uri $createUri" in workflow
    assert "release_id=$releaseId" in workflow
    assert "steps.create_draft_release.outputs.release_id" in workflow
    assert "current.upload_url" in workflow
    assert "An existing or concurrently created Release is never reused" in workflow
    assert "softprops/action-gh-release" not in workflow
    assert "overwrite_files" not in workflow
    assert "cancel-in-progress: false" in workflow


def test_release_workflow_rechecks_master_and_release_id_before_publish() -> None:
    workflow = _workflow_text()
    publication = workflow.split(
        "- name: Publish verified immutable GitHub Release by Release ID", maxsplit=1
    )[1]

    master_lookup = publication.index("git/ref/heads/master")
    release_lookup = publication.index("releases/$releaseId")
    identity_check = publication.index(
        "Release identity or Draft state changed immediately before publication"
    )
    publish_command = publication.index("Invoke-RestMethod -Method Patch")
    immutable_check = publication.index("GitHub did not report it as immutable")

    assert master_lookup < release_lookup < identity_check < publish_command
    assert publish_command < immutable_check
    assert "steps.create_draft_release.outputs.release_id" in publication
    assert "master advanced after release verification" in publication
    assert "releases/tags/$env:GITHUB_REF_NAME" not in publication


def test_release_workflow_checks_exact_assets_before_sensitive_phases() -> None:
    workflow = _workflow_text()

    assert "Local Release asset set is incorrect" in workflow
    assert "Draft Release assets changed outside this workflow" in workflow
    assert (
        "Draft Release identity, state, or exact asset set changed after upload"
        in workflow
    )
    assert "Draft Release asset set changed before redownload" in workflow
    assert "Release assets changed immediately before publication" in workflow
    assert workflow.count("kaito-installer-$env:KAITO_VERSION.exe") >= 4


def test_release_workflow_validates_exact_asset_sets_fail_closed() -> None:
    workflow = _workflow_text()

    assert "Invalid bundled checksum line" in workflow
    assert "Duplicate bundled checksum entry" in workflow
    assert "bundled/SHA256SUMS contains no checksum entries" in workflow
    assert "SHA256SUMS must contain exactly four entries" in workflow
    assert "Published SHA256SUMS file set is incorrect" in workflow
    assert "Published release metadata asset set is incorrect" in workflow


def test_release_scripts_are_repeatable_and_windows_powershell_compatible() -> None:
    build = (REPOSITORY_ROOT / "tools" / "build_release_rehearsal.ps1").read_text(
        encoding="utf-8"
    )
    sign = (REPOSITORY_ROOT / "tools" / "sign_windows.ps1").read_text(encoding="utf-8")
    sign_test = (REPOSITORY_ROOT / "tools" / "test_sign_windows.ps1").read_text(
        encoding="utf-8"
    )
    verify = (REPOSITORY_ROOT / "tools" / "verify_release_rehearsal.ps1").read_text(
        encoding="utf-8"
    )
    sbom = (REPOSITORY_ROOT / "tools" / "generate_sbom.py").read_text(encoding="utf-8")

    assert "RandomNumberGenerator]::GetBytes(24)" not in build
    assert "RandomNumberGenerator]::GetBytes(24)" not in sign_test
    assert "RandomNumberGenerator]::Create()" in build
    assert "RandomNumberGenerator]::Create()" in sign_test
    assert "Add-Content (Join-Path $ArtifactsDir 'bundled-sha256.txt')" not in build
    assert "Set-Content (Join-Path $ArtifactsDir 'bundled-sha256.txt')" in build
    assert (
        "Add-Content (Join-Path $ArtifactsDir 'redownloaded-sha256.txt')" not in verify
    )
    assert "Set-Content (Join-Path $ArtifactsDir 'redownloaded-sha256.txt')" in verify
    assert "Resolve-Path $Candidate | ForEach-Object { $_.Path }" in sign
    assert sign.count("$previousErrorActionPreference = $ErrorActionPreference") >= 2
    assert "$previousErrorActionPreference = $ErrorActionPreference" in verify
    assert "except metadata.PackageNotFoundError as exc:" in sbom
