from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BUILD_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"
PUBLISH_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "release-publish.yml"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _assert_manual_only(workflow: str) -> None:
    assert "workflow_dispatch:" in workflow
    assert "\n  pull_request:" not in workflow
    assert "\n  push:" not in workflow
    assert "\n  schedule:" not in workflow
    assert "\n  workflow_call:" not in workflow


def _assert_actions_are_commit_pinned(workflow: str) -> None:
    lines = [line.strip() for line in workflow.splitlines() if "uses:" in line]
    assert lines
    for line in lines:
        assert re.search(r"uses:\s+[^\s]+@[0-9a-f]{40}(?:\s|$)", line), line


def test_tag_workflow_creates_only_a_new_verified_draft() -> None:
    workflow = _text(BUILD_PATH)

    early_guard = workflow.index("- name: Reject any existing Release")
    build = workflow.index("- name: Build executable")
    late_guard = workflow.index(
        "- name: Reconfirm Release is still absent before asset upload"
    )
    create = workflow.index(
        "- name: Create a new draft GitHub Release with verified assets"
    )
    verify = workflow.index("- name: Verify redownloaded draft Release package")
    record = workflow.index("- name: Record verified draft release")

    assert early_guard < build < late_guard < create < verify < record
    assert workflow.count("Refusing to reuse or overwrite") == 2
    assert "./tools/create_draft_release.ps1" in workflow
    assert "steps.draft_release.outputs.id" in workflow
    assert "gh release edit" not in workflow
    assert "draft=false" not in workflow
    assert "overwrite_files" not in workflow
    assert "Publish verified GitHub Release" not in workflow
    assert "cancel-in-progress: false" in workflow


def test_atomic_draft_creator_refuses_reuse_and_validates_asset_identity() -> None:
    script = _text(REPOSITORY_ROOT / "tools" / "create_draft_release.ps1")

    assert "Exactly five release assets are required" in script
    assert "Existing Releases are never reused or overwritten" in script
    assert "-Method Post" in script
    assert "release.upload_url" in script
    assert "Release became public during asset upload" in script
    assert "Draft Release asset count mismatch" in script
    assert "Compare-Object $expectedNames $actualNames" in script
    assert "-Method Patch" not in script
    assert "draft=false" not in script


def test_tag_workflow_uses_shared_fail_closed_verifier() -> None:
    workflow = _text(BUILD_PATH)

    assert "Invalid bundled checksum line" in workflow
    assert "Duplicate bundled checksum entry" in workflow
    assert "bundled/SHA256SUMS contains no checksum entries" in workflow
    assert "./tools/verify_release_package.ps1" in workflow
    assert "-Profile production" in workflow
    assert "-ReferenceChecksumsPath 'dist/SHA256SUMS'" in workflow
    assert "-ArtifactsDir 'artifacts/publication'" in workflow


def test_tag_workflow_requires_signed_production_artifacts() -> None:
    workflow = _text(BUILD_PATH)
    header = workflow.split("steps:", maxsplit=1)[0]

    assert "environment:" in header
    assert "name: production" in header
    assert "WINDOWS_SIGNING_MODE: required" in workflow
    assert "Validate Windows signing configuration" in workflow
    assert workflow.count("-Mode $env:WINDOWS_SIGNING_MODE") == 3


def test_publication_workflow_is_manual_and_fixed_to_exact_evidence() -> None:
    workflow = _text(PUBLISH_PATH)

    _assert_manual_only(workflow)
    _assert_actions_are_commit_pinned(workflow)
    assert "PUBLISH_VERIFIED_RELEASE" in workflow
    for input_name in ("tag:", "target_commit:", "release_id:", "build_run_id:"):
        assert input_name in workflow
    assert "environment:\n      name: production" in workflow
    assert "actions: read" in workflow
    assert "contents: write" in workflow
    assert "refs/heads/master" in workflow
    assert "git/ref/heads/master" in workflow
    assert "git/ref/tags/$env:INPUT_TAG" in workflow
    assert "releases/$env:INPUT_RELEASE_ID" in workflow
    assert "actions/runs/$env:INPUT_BUILD_RUN_ID" in workflow
    assert "gh run download" in workflow
    assert "--name kaito-release-verification" in workflow
    assert "gh release download" in workflow
    assert "./tools/verify_release_package.ps1" in workflow
    assert "-Profile production" in workflow
    assert "-ReferenceChecksumsPath $env:KAITO_REFERENCE_CHECKSUMS" in workflow


def test_publication_occurs_only_after_reverification_and_live_recheck() -> None:
    workflow = _text(PUBLISH_PATH)

    identity = workflow.index(
        "- name: Bind master, tag, Draft Release, and build run identity"
    )
    evidence = workflow.index("- name: Download immutable build evidence")
    download = workflow.index("- name: Redownload exact Draft Release assets")
    verify = workflow.index("- name: Verify exact package before publication")
    live = workflow.index(
        "- name: Recheck live identity and publish only the same verified Draft Release"
    )
    patch = workflow.index("--method PATCH")

    assert identity < evidence < download < verify < live < patch
    assert "master changed before publication" in workflow
    assert "Build run identity changed" in workflow
    assert "Draft Release identity or asset set changed" in workflow
    assert "-f draft=false" in workflow
    assert "gh release edit" not in workflow
