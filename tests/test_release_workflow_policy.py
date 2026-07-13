from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_release_workflow_refuses_public_release_replay() -> None:
    workflow = _workflow_text()

    early_guard = workflow.index("- name: Reject an existing public Release")
    build = workflow.index("- name: Build executable")
    upload_guard = workflow.index(
        "- name: Reconfirm Release is absent or still draft before asset upload"
    )
    release_action = workflow.index(
        "- name: Create draft GitHub Release with verified assets"
    )
    post_upload_guard = workflow.index(
        "- name: Confirm Release remains draft before verification"
    )
    verification = workflow.index("- name: Redownload and verify draft Release assets")
    publication = workflow.index("- name: Publish verified GitHub Release")

    assert early_guard < build < upload_guard < release_action
    assert release_action < post_upload_guard < verification < publication
    assert workflow.count("Refusing to overwrite public assets") == 2
    assert "draft: true" in workflow
    assert "overwrite_files: true" in workflow
    assert "cancel-in-progress: false" in workflow


def test_release_workflow_rechecks_master_and_release_identity_before_publish() -> None:
    workflow = _workflow_text()
    publication = workflow.split("- name: Publish verified GitHub Release", maxsplit=1)[
        1
    ]

    master_lookup = publication.index("git/ref/heads/master")
    release_lookup = publication.index("releases/tags/$env:GITHUB_REF_NAME")
    identity_check = publication.index("Release identity changed before publication")
    publish_command = publication.index("gh release edit")

    assert master_lookup < release_lookup < identity_check < publish_command
    assert "steps.draft_release.outputs.id" in publication
    assert "master advanced after release verification" in publication


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
