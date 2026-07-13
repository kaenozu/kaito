from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

APPROVAL_MARKER = "KAITO_PRODUCTION_SIGNING_APPROVAL_V1"
CONSUMED_MARKER = "KAITO_PRODUCTION_SIGNING_AUTHORIZATION_CONSUMED_V1"
APPROVAL_KEYS = (
    "repository",
    "workflow",
    "target_commit",
    "nonce",
    "expires_at",
    "decision",
)
WRITE_PERMISSIONS = {"write", "maintain", "admin"}
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
NONCE_PATTERN = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True)
class Expectation:
    repository: str
    issue_number: int
    approval_comment_id: int
    target_commit: str
    nonce: str
    requester: str
    run_id: str
    run_attempt: str
    max_lifetime_minutes: int = 30


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


class GitHubApi:
    def __init__(self, *, token: str, api_url: str) -> None:
        if not token:
            raise RuntimeError("GH_TOKEN is required.")
        self._token = token
        self._api_url = api_url.rstrip("/")

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self._api_url}/{path.lstrip('/')}"
        data = None
        if payload is not None:
            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "kaito-production-signing-authorization",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"GitHub API {method} {path} failed with HTTP {exc.code}: {body}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"GitHub API {method} {path} failed: {exc}") from exc
        if not raw:
            return None
        return json.loads(raw.decode("utf-8"))

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        return self._request("POST", path, payload=payload)

    def list_issue_comments(
        self, repository: str, issue_number: int
    ) -> list[dict[str, Any]]:
        comments: list[dict[str, Any]] = []
        page = 1
        while True:
            page_items = self.get(
                f"repos/{repository}/issues/{issue_number}/comments?per_page=100&page={page}"
            )
            if not isinstance(page_items, list):
                raise RuntimeError("GitHub issue comments response was not a list.")
            comments.extend(page_items)
            if len(page_items) < 100:
                return comments
            page += 1


def parse_timestamp(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include a timezone.")
    return parsed.astimezone(UTC)


def parse_record(body: str, marker: str) -> dict[str, str]:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if not lines or lines[0] != marker:
        raise ValueError(f"Comment must begin with {marker}.")
    record: dict[str, str] = {}
    for line in lines[1:]:
        if "=" not in line:
            raise ValueError(f"Invalid authorization line: {line!r}")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise ValueError(f"Invalid authorization line: {line!r}")
        if key in record:
            raise ValueError(f"Duplicate authorization key: {key}")
        record[key] = value
    return record


def _check(condition: bool, name: str, pass_detail: str, fail_detail: str) -> Check:
    return Check(
        name, "PASS" if condition else "FAIL", pass_detail if condition else fail_detail
    )


def evaluate_snapshot(
    snapshot: dict[str, Any], expectation: Expectation, *, now: datetime
) -> list[Check]:
    now = now.astimezone(UTC)
    issue = snapshot["issue"]
    comment = snapshot["comment"]
    permission = snapshot["permission"]
    consumption_comments = snapshot["consumption_comments"]
    commit = snapshot["commit"]
    repository = snapshot["repository"]
    default_ref = snapshot["default_ref"]
    checks: list[Check] = []

    checks.append(
        _check(
            issue.get("state") == "open" and "pull_request" not in issue,
            "authorization_issue",
            "Authorization issue is open and is not a pull request.",
            "Authorization issue must be open and must not be a pull request.",
        )
    )
    title = str(issue.get("title") or "")
    checks.append(
        _check(
            title.startswith("[Production signing authorization]"),
            "authorization_issue_title",
            "Authorization issue title has the required prefix.",
            "Authorization issue title must start with [Production signing authorization].",
        )
    )
    expected_issue_suffix = f"/issues/{expectation.issue_number}"
    checks.append(
        _check(
            str(comment.get("issue_url") or "").endswith(expected_issue_suffix),
            "comment_issue_identity",
            "Approval comment belongs to the requested issue.",
            "Approval comment does not belong to the requested issue.",
        )
    )

    approver = str((comment.get("user") or {}).get("login") or "")
    approver_type = str((comment.get("user") or {}).get("type") or "")
    checks.append(
        _check(
            bool(approver)
            and approver.casefold() != expectation.requester.casefold()
            and approver_type == "User",
            "independent_human_approver",
            f"Approval was submitted by independent human {approver}.",
            "Approval must be submitted by a human other than the workflow requester.",
        )
    )
    permission_name = str(permission.get("permission") or "").lower()
    checks.append(
        _check(
            permission_name in WRITE_PERMISSIONS,
            "approver_permission",
            f"Approver permission is {permission_name}.",
            f"Approver permission must be write, maintain, or admin; got {permission_name or 'none'}.",
        )
    )

    try:
        record = parse_record(str(comment.get("body") or ""), APPROVAL_MARKER)
        record_error = ""
    except ValueError as exc:
        record = {}
        record_error = str(exc)
    checks.append(
        _check(
            not record_error and tuple(record.keys()) == APPROVAL_KEYS,
            "approval_record_shape",
            "Approval record has the exact required fields and order.",
            record_error or "Approval record fields or field order are incorrect.",
        )
    )

    expected_values = {
        "repository": expectation.repository,
        "workflow": "production-signing-canary",
        "target_commit": expectation.target_commit,
        "nonce": expectation.nonce,
        "decision": "APPROVE",
    }
    for key, expected in expected_values.items():
        checks.append(
            _check(
                record.get(key) == expected,
                f"approval_{key}",
                f"Approval {key} matches the requested operation.",
                f"Approval {key} mismatch.",
            )
        )

    checks.append(
        _check(
            SHA_PATTERN.fullmatch(expectation.target_commit) is not None,
            "target_commit_format",
            "Target commit is a lowercase 40-character SHA.",
            "Target commit must be a lowercase 40-character SHA.",
        )
    )
    checks.append(
        _check(
            NONCE_PATTERN.fullmatch(expectation.nonce) is not None,
            "nonce_format",
            "Nonce is a lowercase 32-character hexadecimal value.",
            "Nonce must be a lowercase 32-character hexadecimal value.",
        )
    )
    checks.append(
        _check(
            str(commit.get("sha") or "") == expectation.target_commit,
            "target_commit_exists",
            "Target commit exists and resolves exactly.",
            "Target commit could not be resolved exactly.",
        )
    )

    default_branch = str(repository.get("default_branch") or "")
    default_sha = str((default_ref.get("object") or {}).get("sha") or "")
    checks.append(
        _check(
            default_branch == "master",
            "default_branch_identity",
            "Repository default branch is master.",
            f"Repository default branch must be master; got {default_branch or 'none'}.",
        )
    )
    checks.append(
        _check(
            default_sha == expectation.target_commit,
            "target_is_current_default_head",
            "Target commit is the current default-branch HEAD.",
            "Target commit must equal the current default-branch HEAD.",
        )
    )

    try:
        created_at = parse_timestamp(str(comment.get("created_at") or ""))
        updated_at = parse_timestamp(str(comment.get("updated_at") or ""))
        expires_at = parse_timestamp(record.get("expires_at", ""))
        time_error = ""
    except (TypeError, ValueError) as exc:
        created_at = updated_at = expires_at = now
        time_error = str(exc)
    checks.append(
        _check(
            not time_error and created_at == updated_at,
            "approval_not_edited",
            "Approval comment has not been edited.",
            time_error or "Edited approval comments are rejected.",
        )
    )
    checks.append(
        _check(
            not time_error and created_at <= now <= expires_at,
            "approval_current",
            "Approval is currently valid.",
            time_error or "Approval is not yet valid or has expired.",
        )
    )
    checks.append(
        _check(
            not time_error
            and expires_at
            <= created_at + timedelta(minutes=expectation.max_lifetime_minutes),
            "approval_lifetime",
            "Approval lifetime is within the configured maximum.",
            time_error
            or f"Approval lifetime exceeds {expectation.max_lifetime_minutes} minutes.",
        )
    )

    reused = False
    for prior in consumption_comments:
        body = str(prior.get("body") or "")
        if not body.startswith(CONSUMED_MARKER):
            continue
        try:
            consumed = parse_record(body, CONSUMED_MARKER)
        except ValueError:
            continue
        if (
            consumed.get("approval_comment_id") == str(expectation.approval_comment_id)
            or consumed.get("nonce") == expectation.nonce
        ):
            reused = True
            break
    checks.append(
        _check(
            not reused,
            "authorization_not_consumed",
            "Approval comment and nonce have not been consumed.",
            "Approval comment or nonce has already been consumed.",
        )
    )
    return checks


def overall_status(checks: list[Check]) -> str:
    return (
        "PASS" if checks and all(check.status == "PASS" for check in checks) else "FAIL"
    )


def build_consumption_comment(
    expectation: Expectation, *, approver: str, consumed_at: datetime
) -> str:
    run_url = (
        f"https://github.com/{expectation.repository}/actions/runs/{expectation.run_id}"
    )
    lines = [
        CONSUMED_MARKER,
        f"approval_comment_id={expectation.approval_comment_id}",
        f"nonce={expectation.nonce}",
        f"target_commit={expectation.target_commit}",
        f"requester={expectation.requester}",
        f"approver={approver}",
        f"workflow_run={run_url}",
        f"run_attempt={expectation.run_attempt}",
        f"consumed_at={consumed_at.astimezone(UTC).isoformat().replace('+00:00', 'Z')}",
    ]
    return "\n".join(lines)


def fetch_snapshot(api: GitHubApi, expectation: Expectation) -> dict[str, Any]:
    repository = api.get(f"repos/{expectation.repository}")
    default_branch = str(repository.get("default_branch") or "")
    default_ref = api.get(
        f"repos/{expectation.repository}/git/ref/heads/{urllib.parse.quote(default_branch, safe='')}"
    )
    issue = api.get(f"repos/{expectation.repository}/issues/{expectation.issue_number}")
    comment = api.get(
        f"repos/{expectation.repository}/issues/comments/{expectation.approval_comment_id}"
    )
    approver = str((comment.get("user") or {}).get("login") or "")
    permission = api.get(
        f"repos/{expectation.repository}/collaborators/{urllib.parse.quote(approver, safe='')}/permission"
    )
    commit = api.get(
        f"repos/{expectation.repository}/commits/{expectation.target_commit}"
    )
    comments = api.list_issue_comments(expectation.repository, expectation.issue_number)
    return {
        "repository": repository,
        "default_ref": default_ref,
        "issue": issue,
        "comment": comment,
        "permission": permission,
        "commit": commit,
        "consumption_comments": comments,
    }


def write_evidence(
    path: Path,
    *,
    expectation: Expectation,
    checks: list[Check],
    snapshot: dict[str, Any],
    consumption_comment_id: int | None,
    evaluated_at: datetime,
) -> None:
    approver = str((snapshot["comment"].get("user") or {}).get("login") or "")
    evidence = {
        "schema_version": 1,
        "result": overall_status(checks),
        "evaluated_at": evaluated_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "repository": expectation.repository,
        "issue_number": expectation.issue_number,
        "approval_comment_id": expectation.approval_comment_id,
        "consumption_comment_id": consumption_comment_id,
        "target_commit": expectation.target_commit,
        "nonce": expectation.nonce,
        "requester": expectation.requester,
        "approver": approver,
        "checks": [asdict(check) for check in checks],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def append_outputs(
    path: str | None, *, expectation: Expectation, approver: str
) -> None:
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(f"target_commit={expectation.target_commit}\n")
        handle.write(f"authorization_issue={expectation.issue_number}\n")
        handle.write(f"approver={approver}\n")
        handle.write(f"approval_comment_id={expectation.approval_comment_id}\n")
        handle.write(f"nonce={expectation.nonce}\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify and consume an independent production-signing authorization."
    )
    parser.add_argument("--repository", required=True)
    parser.add_argument("--authorization-issue", required=True, type=int)
    parser.add_argument("--approval-comment-id", required=True, type=int)
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--requester", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--evidence-path", type=Path, required=True)
    parser.add_argument("--max-lifetime-minutes", type=int, default=30)
    args = parser.parse_args()

    expectation = Expectation(
        repository=args.repository,
        issue_number=args.authorization_issue,
        approval_comment_id=args.approval_comment_id,
        target_commit=args.target_commit,
        nonce=args.nonce,
        requester=args.requester,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        max_lifetime_minutes=args.max_lifetime_minutes,
    )
    now = datetime.now(UTC)
    api = GitHubApi(
        token=os.environ.get("GH_TOKEN", ""),
        api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
    )
    snapshot = fetch_snapshot(api, expectation)
    checks = evaluate_snapshot(snapshot, expectation, now=now)
    status = overall_status(checks)
    consumption_comment_id: int | None = None

    if status == "PASS":
        approver = str((snapshot["comment"].get("user") or {}).get("login") or "")
        body = build_consumption_comment(
            expectation, approver=approver, consumed_at=now
        )
        response = api.post(
            f"repos/{expectation.repository}/issues/{expectation.issue_number}/comments",
            {"body": body},
        )
        consumption_comment_id = int(response["id"])
        append_outputs(
            os.environ.get("GITHUB_OUTPUT"), expectation=expectation, approver=approver
        )

    write_evidence(
        args.evidence_path,
        expectation=expectation,
        checks=checks,
        snapshot=snapshot,
        consumption_comment_id=consumption_comment_id,
        evaluated_at=now,
    )
    for check in checks:
        print(f"[{check.status}] {check.name}: {check.detail}")
    print(f"Authorization result: {status}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
