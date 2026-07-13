from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "production-signing-canary.yml"
VERIFIER_PATH = ROOT / "tools" / "verify_production_signing_authorization.py"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_authorization_job_is_trusted_secretless_and_single_use() -> None:
    workflow = _text(WORKFLOW_PATH)
    verifier = _text(VERIFIER_PATH)

    assert "workflow_dispatch:" in workflow
    assert "\n  pull_request:" not in workflow
    assert "\n  push:" not in workflow
    assert "permissions: {}" in workflow
    assert "group: production-signing-canary" in workflow
    assert "cancel-in-progress: false" in workflow

    authorize, sign = workflow.split("  sign-canary:\n", 1)
    assert "name: authorize-independent-production-signing" in authorize
    assert "issues: write" in authorize
    assert "ref: ${{ github.sha }}" in authorize
    assert "ref: ${{ inputs.target_commit }}" not in authorize
    assert "WINDOWS_CERTIFICATE_BASE64" not in authorize
    assert "WINDOWS_CERTIFICATE_PASSWORD" not in authorize
    assert "WINDOWS_TIMESTAMP_URL" not in authorize

    assert "name: sign-production-canary-after-independent-authorization" in sign
    assert "needs: authorize-production-signing" in sign
    assert "environment:\n      name: production" in sign
    assert (
        "ref: ${{ needs.authorize-production-signing.outputs.target_commit }}" in sign
    )
    assert "WINDOWS_CERTIFICATE_BASE64" in sign
    assert "WINDOWS_CERTIFICATE_PASSWORD" in sign
    assert "WINDOWS_TIMESTAMP_URL" in sign
    assert "issues: write" not in sign
    assert "contents: write" not in workflow
    assert "gh release" not in workflow
    assert "git/refs/tags" not in workflow

    assert "KAITO_PRODUCTION_SIGNING_APPROVAL_V1" in verifier
    assert "KAITO_PRODUCTION_SIGNING_AUTHORIZATION_CONSUMED_V1" in verifier
    assert "target_is_current_default_head" in verifier
    assert "approval_not_edited" in verifier
    assert "authorization_not_consumed" in verifier
    assert "WRITE_PERMISSIONS" in verifier


def test_all_actions_are_commit_pinned() -> None:
    workflow = _text(WORKFLOW_PATH)
    uses_lines = [line.strip() for line in workflow.splitlines() if "uses:" in line]

    assert uses_lines
    for line in uses_lines:
        assert re.search(r"uses:\s+[^\s]+@[0-9a-f]{40}(?:\s|$)", line), line
