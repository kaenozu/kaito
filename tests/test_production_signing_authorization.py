from __future__ import annotations

import importlib.util
import io
import sys
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

UTC = timezone.utc
MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "verify_production_signing_authorization.py"
)
SPEC = importlib.util.spec_from_file_location(
    "verify_production_signing_authorization", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

APPROVAL_MARKER = MODULE.APPROVAL_MARKER
CONSUMED_MARKER = MODULE.CONSUMED_MARKER
Expectation = MODULE.Expectation
GitHubApi = MODULE.GitHubApi
evaluate_snapshot = MODULE.evaluate_snapshot
overall_status = MODULE.overall_status

NOW = datetime(2026, 7, 13, 8, 30, tzinfo=UTC)


def _expectation() -> Any:
    return Expectation(
        repository="kaenozu/kaito",
        issue_number=20,
        approval_comment_id=12345,
        target_commit="a" * 40,
        nonce="b" * 32,
        requester="requester",
        run_id="999",
        run_attempt="1",
    )


def _approval_body(expectation: Any, expires_at: datetime) -> str:
    return "\n".join(
        [
            APPROVAL_MARKER,
            f"repository={expectation.repository}",
            "workflow=production-signing-canary",
            f"target_commit={expectation.target_commit}",
            f"nonce={expectation.nonce}",
            f"expires_at={expires_at.isoformat().replace('+00:00', 'Z')}",
            "decision=APPROVE",
        ]
    )


def _snapshot() -> dict[str, Any]:
    expectation = _expectation()
    created_at = NOW - timedelta(minutes=5)
    return {
        "repository": {"default_branch": "master"},
        "default_ref": {"object": {"sha": expectation.target_commit}},
        "issue": {
            "state": "open",
            "title": "[Production signing authorization] canary for reviewed commit",
        },
        "comment": {
            "issue_url": f"https://api.github.com/repos/kaenozu/kaito/issues/{expectation.issue_number}",
            "body": _approval_body(expectation, NOW + timedelta(minutes=5)),
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
            "updated_at": created_at.isoformat().replace("+00:00", "Z"),
            "user": {"login": "reviewer", "type": "User"},
        },
        "permission": {"permission": "write"},
        "commit": {"sha": expectation.target_commit},
        "consumption_comments": [],
    }


def _statuses(snapshot: dict[str, Any]) -> dict[str, str]:
    checks = evaluate_snapshot(snapshot, _expectation(), now=NOW)
    return {check.name: check.status for check in checks}


def test_independent_fresh_write_approval_passes() -> None:
    checks = evaluate_snapshot(_snapshot(), _expectation(), now=NOW)

    assert overall_status(checks) == "PASS"
    assert {check.status for check in checks} == {"PASS"}


def test_self_approval_and_bot_approval_fail() -> None:
    snapshot = _snapshot()
    snapshot["comment"]["user"] = {"login": "requester", "type": "Bot"}

    statuses = _statuses(snapshot)

    assert statuses["independent_human_approver"] == "FAIL"


def test_read_only_reviewer_and_edited_comment_fail() -> None:
    snapshot = _snapshot()
    snapshot["permission"] = {"permission": "read"}
    snapshot["comment"]["updated_at"] = NOW.isoformat().replace("+00:00", "Z")

    statuses = _statuses(snapshot)

    assert statuses["approver_permission"] == "FAIL"
    assert statuses["approval_not_edited"] == "FAIL"


def test_expired_or_overlong_approval_fails() -> None:
    expectation = _expectation()
    snapshot = _snapshot()
    created_at = NOW - timedelta(minutes=31)
    snapshot["comment"]["created_at"] = created_at.isoformat().replace("+00:00", "Z")
    snapshot["comment"]["updated_at"] = created_at.isoformat().replace("+00:00", "Z")
    snapshot["comment"]["body"] = _approval_body(
        expectation, NOW + timedelta(minutes=31)
    )

    statuses = _statuses(snapshot)

    assert statuses["approval_lifetime"] == "FAIL"


def test_reused_comment_or_nonce_fails() -> None:
    expectation = _expectation()
    snapshot = _snapshot()
    snapshot["consumption_comments"] = [
        {
            "body": "\n".join(
                [
                    CONSUMED_MARKER,
                    f"approval_comment_id={expectation.approval_comment_id}",
                    f"nonce={expectation.nonce}",
                ]
            )
        }
    ]

    statuses = _statuses(snapshot)

    assert statuses["authorization_not_consumed"] == "FAIL"


def test_extra_or_reordered_approval_fields_fail_closed() -> None:
    snapshot = _snapshot()
    lines = snapshot["comment"]["body"].splitlines()
    lines.insert(2, "unexpected=value")
    snapshot["comment"]["body"] = "\n".join(lines)

    statuses = _statuses(snapshot)

    assert statuses["approval_record_shape"] == "FAIL"


def test_non_default_branch_target_fails() -> None:
    snapshot = _snapshot()
    snapshot["default_ref"] = {"object": {"sha": "c" * 40}}

    statuses = _statuses(snapshot)

    assert statuses["target_is_current_default_head"] == "FAIL"


def test_missing_snapshot_values_fail_without_exception() -> None:
    checks = evaluate_snapshot({}, _expectation(), now=NOW)

    assert overall_status(checks) == "FAIL"
    statuses = {check.name: check.status for check in checks}
    assert statuses["authorization_issue"] == "FAIL"
    assert statuses["approver_permission"] == "FAIL"
    assert statuses["target_commit_exists"] == "FAIL"


def test_allow_404_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    error = urllib.error.HTTPError(
        "https://api.github.test/missing",
        404,
        "Not Found",
        hdrs=None,
        fp=io.BytesIO(b'{"message":"Not Found"}'),
    )

    def raise_404(*_args: Any, **_kwargs: Any) -> Any:
        raise error

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", raise_404)
    api = GitHubApi(token="test-token", api_url="https://api.github.test")

    assert api.get("missing", allow_404=True) is None


def test_non_404_remains_operational_error(monkeypatch: pytest.MonkeyPatch) -> None:
    error = urllib.error.HTTPError(
        "https://api.github.test/failure",
        500,
        "Server Error",
        hdrs=None,
        fp=io.BytesIO(b'{"message":"failure"}'),
    )

    def raise_500(*_args: Any, **_kwargs: Any) -> Any:
        raise error

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", raise_500)
    api = GitHubApi(token="test-token", api_url="https://api.github.test")

    with pytest.raises(RuntimeError, match="HTTP 500"):
        api.get("failure", allow_404=True)
