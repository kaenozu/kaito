from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "tools" / "verify_pr_approval_gate.py"
)
SPEC = importlib.util.spec_from_file_location("verify_pr_approval_gate", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

Expectation = MODULE.Expectation
evaluate_snapshot = MODULE.evaluate_snapshot


def _expectation() -> Any:
    return Expectation(
        repository="kaenozu/kaito",
        pr_number=11,
        expected_head="a" * 40,
        expected_base_ref="master",
        expected_base_sha="b" * 40,
        expected_ahead=2,
        expected_behind=0,
        expected_files=frozenset({"one", "two"}),
        required_workflows=frozenset({"CI", "Release hardening checks"}),
    )


def _snapshot() -> dict[str, Any]:
    expected = _expectation()
    return {
        "pr": {
            "state": "open",
            "merged": False,
            "draft": False,
            "head": {"sha": expected.expected_head},
            "base": {"ref": "master"},
            "user": {"login": "author"},
        },
        "base_sha": expected.expected_base_sha,
        "compare": {
            "ahead_by": 2,
            "behind_by": 0,
            "files": [{"filename": "one"}, {"filename": "two"}],
        },
        "reviews": [
            {
                "state": "APPROVED",
                "commit_id": expected.expected_head,
                "user": {"login": "reviewer"},
            }
        ],
        "workflow_runs": [
            {"name": "CI", "status": "completed", "conclusion": "success"},
            {
                "name": "Release hardening checks",
                "status": "completed",
                "conclusion": "success",
            },
        ],
        "reviewer_permissions": {"reviewer": "write"},
        "unresolved_threads": 0,
        "auto_merge_enabled": False,
    }


def test_fixed_head_gate_passes_complete_snapshot() -> None:
    checks = evaluate_snapshot(_snapshot(), _expectation())

    assert {check.status for check in checks} == {"PASS"}


def test_fixed_head_gate_blocks_without_independent_approval() -> None:
    snapshot = _snapshot()
    snapshot["reviews"] = []

    checks = evaluate_snapshot(snapshot, _expectation())
    approval = next(check for check in checks if check.name == "independent_approval")

    assert approval.status == "BLOCKED"


def test_fixed_head_gate_fails_unexpected_file_and_stale_approval() -> None:
    expected = _expectation()
    snapshot = _snapshot()
    snapshot["compare"]["files"].append({"filename": "unexpected"})
    snapshot["reviews"][0]["commit_id"] = "c" * 40

    checks = evaluate_snapshot(snapshot, expected)
    statuses = {check.name: check.status for check in checks}

    assert statuses["exact_files"] == "FAIL"
    assert statuses["independent_approval"] == "BLOCKED"
