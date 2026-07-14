from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ROUNDTRIP_PATH = (
    REPOSITORY_ROOT / ".github" / "workflows" / "release-draft-roundtrip.yml"
)
PRODUCTION_CANARY_PATH = (
    REPOSITORY_ROOT / ".github" / "workflows" / "production-signing-canary.yml"
)
APPROVAL_GATE_PATH = (
    REPOSITORY_ROOT / ".github" / "workflows" / "release-approval-gate.yml"
)
OPERATIONS_DOC_PATH = REPOSITORY_ROOT / "docs" / "RELEASE_OPERATIONS.md"
SIGNING_AUTH_DOC_PATH = REPOSITORY_ROOT / "docs" / "PRODUCTION_SIGNING_AUTHORIZATION.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _assert_manual_only(workflow: str) -> None:
    assert "workflow_dispatch:" in workflow
    assert "\n  pull_request:" not in workflow
    assert "\n  push:" not in workflow
    assert "\n  schedule:" not in workflow
    assert "\n  workflow_call:" not in workflow


def _assert_actions_are_commit_pinned(workflow: str) -> None:
    uses_lines = [line.strip() for line in workflow.splitlines() if "uses:" in line]
    assert uses_lines
    for line in uses_lines:
        assert re.search(r"uses:\s+[^\s]+@[0-9a-f]{40}(?:\s|$)", line), line


def test_draft_release_roundtrip_is_manual_draft_only_and_self_cleaning() -> None:
    workflow = _text(ROUNDTRIP_PATH)

    _assert_manual_only(workflow)
    _assert_actions_are_commit_pinned(workflow)
    assert "confirmation:" in workflow
    assert "CREATE_AND_DELETE_DRAFT" in workflow
    assert "permissions:\n  contents: write" in workflow
    assert "gh release create" in workflow
    assert "--draft" in workflow
    assert "gh release download" in workflow
    assert "-Profile rehearsal" in workflow
    assert "gh release delete" in workflow
    assert "git/refs/tags" in workflow
    assert "if: always()" in workflow
    assert "Refusing to delete an unexpectedly public Release automatically" in workflow
    assert (
        "Refusing to delete the tag associated with an unexpectedly public Release"
        in workflow
    )
    assert "git ls-remote" not in workflow
    assert "--draft=false" not in workflow
    assert "gh release edit" not in workflow
    assert "WINDOWS_CERTIFICATE_BASE64" not in workflow
    assert "WINDOWS_CERTIFICATE_PASSWORD" not in workflow


def test_production_signing_canary_requires_consumed_independent_authorization() -> (
    None
):
    workflow = _text(PRODUCTION_CANARY_PATH)

    _assert_manual_only(workflow)
    _assert_actions_are_commit_pinned(workflow)
    assert "SIGN_CANARY_WITH_PRODUCTION_CERT" in workflow
    assert "authorization_issue:" in workflow
    assert "approval_comment_id:" in workflow
    assert "target_commit:" in workflow
    assert "nonce:" in workflow
    assert "permissions: {}" in workflow
    assert "name: authorize-independent-production-signing" in workflow
    assert "issues: write" in workflow
    assert "verify_production_signing_authorization.py" in workflow
    assert "name: sign-production-canary-after-independent-authorization" in workflow
    assert "needs: authorize-production-signing" in workflow
    assert "environment:\n      name: production" in workflow
    assert "WINDOWS_CERTIFICATE_BASE64" in workflow
    assert "WINDOWS_CERTIFICATE_PASSWORD" in workflow
    assert "WINDOWS_TIMESTAMP_URL" in workflow
    assert "-Mode required" in workflow
    assert "-VerificationMode strict" in workflow
    assert "-TimestampUrl $env:WINDOWS_TIMESTAMP_URL" in workflow
    assert "CN=kaito CI signing test" in workflow
    assert "Remove-Item canary -Recurse -Force" in workflow
    assert "metadata-only signing evidence" in workflow
    assert "gh release" not in workflow
    assert "git/refs/tags" not in workflow
    assert "contents: write" not in workflow

    authorize_section, sign_section = workflow.split("  sign-canary:\n", 1)
    assert "ref: ${{ github.sha }}" in authorize_section
    assert "ref: ${{ inputs.target_commit }}" not in authorize_section
    assert "WINDOWS_CERTIFICATE_BASE64" not in authorize_section
    assert "WINDOWS_CERTIFICATE_PASSWORD" not in authorize_section
    assert "issues: write" not in sign_section


def test_production_authorization_is_fail_closed_and_single_use() -> None:
    workflow = _text(PRODUCTION_CANARY_PATH)
    authorization = _text(
        REPOSITORY_ROOT / "tools" / "verify_production_signing_authorization.py"
    )
    documentation = _text(SIGNING_AUTH_DOC_PATH)

    assert "KAITO_PRODUCTION_SIGNING_APPROVAL_V1" in authorization
    assert "KAITO_PRODUCTION_SIGNING_AUTHORIZATION_CONSUMED_V1" in authorization
    assert "WRITE_PERMISSIONS" in authorization
    assert "independent_human_approver" in authorization
    assert "approval_not_edited" in authorization
    assert "approval_lifetime" in authorization
    assert "authorization_not_consumed" in authorization
    assert "target_is_current_default_head" in authorization
    assert "allow_404=True" in authorization
    assert "build_consumption_comment" in authorization
    assert "api.post(" in authorization
    assert "consumption_comment_id" in authorization
    assert "cancel-in-progress: false" in workflow
    assert "30 minutes" in documentation
    assert "current `master` HEAD" in documentation


def test_release_approval_gate_is_manual_read_only_and_fixed_head() -> None:
    workflow = _text(APPROVAL_GATE_PATH)

    _assert_manual_only(workflow)
    _assert_actions_are_commit_pinned(workflow)
    assert "VERIFY_FIXED_PR_GATE" in workflow
    assert (
        "permissions:\n  actions: read\n  contents: read\n  pull-requests: read"
        in workflow
    )
    assert "--expected-head" in workflow
    assert "--expected-base-sha" in workflow
    assert "--expected-files" in workflow
    assert "--required-workflows" in workflow
    assert "contents: write" not in workflow
    assert "issues: write" not in workflow
    assert "pull-requests: write" not in workflow
    assert "gh release" not in workflow
    assert "git/refs/tags" not in workflow


def test_repository_protection_and_unified_merge_order_are_explicit() -> None:
    operations = _text(OPERATIONS_DOC_PATH)

    protection = operations.index("Protect `master` before merging")
    merge_process = operations.index("Before merge:")
    assert protection < merge_process
    assert "Do not substitute self-approval" in operations
    assert "unified release and application hardening pull request" in operations
    assert "verify-windows" in operations
    assert "signing-and-sbom" in operations
    assert "build-rehearsal-package" in operations
    assert "verify-redownloaded-package" in operations
    assert "packaged-gui-smoke" in operations
    assert "workflow_dispatch" in operations
    assert "default branch" in operations
    assert "exact current HEAD" in operations


def test_operational_workflows_use_distinct_concurrency_groups() -> None:
    roundtrip = _text(ROUNDTRIP_PATH)
    production = _text(PRODUCTION_CANARY_PATH)
    approval = _text(APPROVAL_GATE_PATH)

    assert "group: draft-release-roundtrip" in roundtrip
    assert "group: production-signing-canary" in production
    assert "group: release-pr-approval-gate-${{ inputs.pr_number }}" in approval
    assert "cancel-in-progress: false" in roundtrip
    assert "cancel-in-progress: false" in production
    assert "cancel-in-progress: false" in approval
