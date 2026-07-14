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
        pr_number=20,
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
        "workflow_runs": [
            {"name": "CI", "status": "completed", "conclusion": "success"},
            {
                "name": "Release hardening checks",
                "status": "completed",
                "conclusion": "success",
            },
        ],
        "unresolved_threads": 0,
        "auto_merge_enabled": False,
    }


def test_fixed_head_gate_passes_without_external_approval() -> None:
    checks = evaluate_snapshot(_snapshot(), _expectation())
    statuses = {check.name: check.status for check in checks}

    assert set(statuses.values()) == {"PASS"}
    assert statuses["solo_maintainer_policy"] == "PASS"
    assert "independent_approval" not in statuses


def test_fixed_head_gate_fails_unexpected_file() -> None:
    snapshot = _snapshot()
    snapshot["compare"]["files"].append({"filename": "unexpected"})

    checks = evaluate_snapshot(snapshot, _expectation())
    statuses = {check.name: check.status for check in checks}

    assert statuses["exact_files"] == "FAIL"
    assert statuses["solo_maintainer_policy"] == "PASS"


def test_fixed_head_gate_fails_draft_or_missing_workflow() -> None:
    snapshot = _snapshot()
    snapshot["pr"]["draft"] = True
    snapshot["workflow_runs"] = []

    checks = evaluate_snapshot(snapshot, _expectation())
    statuses = {check.name: check.status for check in checks}

    assert statuses["ready_for_review"] == "FAIL"
    assert statuses["required_workflows"] == "FAIL"
