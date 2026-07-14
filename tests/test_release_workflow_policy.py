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
    download = workflow.index("- name: Redownload draft Release assets")
    verification = workflow.index("- name: Verify redownloaded draft Release package")
    publication = workflow.index("- name: Publish verified GitHub Release")

    assert early_guard < build < upload_guard < release_action
    assert release_action < post_upload_guard < download < verification < publication
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


def test_release_workflow_uses_shared_fail_closed_verifier() -> None:
    workflow = _workflow_text()

    assert "Invalid bundled checksum line" in workflow
    assert "Duplicate bundled checksum entry" in workflow
    assert "bundled/SHA256SUMS contains no checksum entries" in workflow
    assert "./tools/verify_release_package.ps1" in workflow
    assert "-Profile production" in workflow
    assert "-ReferenceChecksumsPath 'dist/SHA256SUMS'" in workflow
    assert "-ArtifactsDir 'artifacts/publication'" in workflow


def test_release_workflow_requires_production_environment() -> None:
    workflow = _workflow_text()
    job_header = workflow.split("steps:", maxsplit=1)[0]

    assert "environment:" in job_header
    assert "name: production" in job_header


def test_release_workflow_requires_signed_production_artifacts() -> None:
    workflow = _workflow_text()

    assert "WINDOWS_SIGNING_MODE: required" in workflow
    assert "Validate Windows signing configuration" in workflow
    assert workflow.count("-Mode $env:WINDOWS_SIGNING_MODE") == 3
    assert "environment:" in workflow
    assert "name: production" in workflow
