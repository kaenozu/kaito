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


def test_production_signing_canary_is_manual_read_only_and_metadata_only() -> None:
    workflow = _text(PRODUCTION_CANARY_PATH)

    _assert_manual_only(workflow)
    _assert_actions_are_commit_pinned(workflow)
    assert "SIGN_CANARY_WITH_PRODUCTION_CERT" in workflow
    assert "permissions:\n  contents: read" in workflow
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


def test_roundtrip_and_production_canary_use_distinct_concurrency_groups() -> None:
    roundtrip = _text(ROUNDTRIP_PATH)
    production = _text(PRODUCTION_CANARY_PATH)

    assert "group: draft-release-roundtrip" in roundtrip
    assert "group: production-signing-canary" in production
    assert "cancel-in-progress: false" in roundtrip
    assert "cancel-in-progress: false" in production
