from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

API_VERSION = "2022-11-28"
WRITE_PERMISSIONS = {"admin", "maintain", "write"}


@dataclass(frozen=True)
class Expectation:
    repository: str
    pr_number: int
    expected_head: str
    expected_base_ref: str
    expected_base_sha: str
    expected_ahead: int
    expected_behind: int
    expected_files: frozenset[str]
    required_workflows: frozenset[str]


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


class GitHubClient:
    def __init__(self, token: str, api_url: str) -> None:
        self._token = token
        self._api_url = api_url.rstrip("/")

    def _request(
        self,
        method: str,
        url: str,
        body: dict[str, Any] | None = None,
    ) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": API_VERSION,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"GitHub API {exc.code} for {url}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"GitHub API request failed for {url}: {exc.reason}"
            ) from exc

    def get(self, path: str, query: dict[str, str] | None = None) -> Any:
        url = f"{self._api_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        return self._request("GET", url)

    def graphql(self, query: str, variables: dict[str, Any]) -> Any:
        data = self._request(
            "POST",
            "https://api.github.com/graphql",
            {"query": query, "variables": variables},
        )
        errors = data.get("errors", [])
        if errors:
            raise RuntimeError(f"GitHub GraphQL returned errors: {errors}")
        return data["data"]


def _check(
    name: str,
    condition: bool,
    pass_detail: str,
    fail_detail: str,
) -> Check:
    return Check(
        name,
        "PASS" if condition else "FAIL",
        pass_detail if condition else fail_detail,
    )


def evaluate_snapshot(
    snapshot: dict[str, Any],
    expected: Expectation,
) -> list[Check]:
    pr = snapshot["pr"]
    compare = snapshot["compare"]
    checks: list[Check] = []

    checks.append(
        _check(
            "pr_open",
            pr["state"] == "open" and not pr["merged"],
            "PR is open and unmerged.",
            "PR is not open and unmerged.",
        )
    )
    checks.append(
        _check(
            "ready_for_review",
            not pr["draft"],
            "PR is Ready for Review.",
            "PR is still Draft.",
        )
    )
    checks.append(
        _check(
            "head_sha",
            pr["head"]["sha"] == expected.expected_head,
            f"HEAD is {expected.expected_head}.",
            f"HEAD is {pr['head']['sha']}, expected {expected.expected_head}.",
        )
    )
    checks.append(
        _check(
            "base_ref",
            pr["base"]["ref"] == expected.expected_base_ref,
            f"Base ref is {expected.expected_base_ref}.",
            f"Base ref is {pr['base']['ref']}, expected {expected.expected_base_ref}.",
        )
    )
    checks.append(
        _check(
            "current_base_sha",
            snapshot["base_sha"] == expected.expected_base_sha,
            f"Current base SHA is {expected.expected_base_sha}.",
            (
                f"Current base SHA is {snapshot['base_sha']}, "
                f"expected {expected.expected_base_sha}."
            ),
        )
    )
    checks.append(
        _check(
            "ahead",
            compare["ahead_by"] == expected.expected_ahead,
            f"Ahead count is {expected.expected_ahead}.",
            (
                f"Ahead count is {compare['ahead_by']}, "
                f"expected {expected.expected_ahead}."
            ),
        )
    )
    checks.append(
        _check(
            "behind",
            compare["behind_by"] == expected.expected_behind,
            f"Behind count is {expected.expected_behind}.",
            (
                f"Behind count is {compare['behind_by']}, "
                f"expected {expected.expected_behind}."
            ),
        )
    )

    actual_files = frozenset(item["filename"] for item in compare["files"])
    missing = sorted(expected.expected_files - actual_files)
    extra = sorted(actual_files - expected.expected_files)
    checks.append(
        _check(
            "exact_files",
            not missing and not extra,
            f"Exact changed-file set matches ({len(actual_files)} files).",
            f"Changed-file mismatch; missing={missing}, extra={extra}.",
        )
    )

    workflow_runs = snapshot["workflow_runs"]
    latest_by_name: dict[str, dict[str, Any]] = {}
    for run in workflow_runs:
        latest_by_name.setdefault(run["name"], run)
    workflow_failures: list[str] = []
    for name in sorted(expected.required_workflows):
        run = latest_by_name.get(name)
        if run is None:
            workflow_failures.append(f"{name}: missing")
        elif run.get("status") != "completed" or run.get("conclusion") != "success":
            workflow_failures.append(
                f"{name}: {run.get('status')}/{run.get('conclusion')}"
            )
    checks.append(
        _check(
            "required_workflows",
            not workflow_failures,
            "All required workflows completed successfully.",
            f"Required workflow failures: {workflow_failures}.",
        )
    )

    unresolved = int(snapshot["unresolved_threads"])
    checks.append(
        _check(
            "review_threads",
            unresolved == 0,
            "All review threads are resolved.",
            f"{unresolved} review threads remain unresolved.",
        )
    )
    checks.append(
        _check(
            "auto_merge",
            not snapshot["auto_merge_enabled"],
            "Auto-merge is disabled.",
            "Auto-merge is enabled.",
        )
    )

    approvals = []
    for review in snapshot["reviews"]:
        if review.get("state") != "APPROVED":
            continue
        author = review.get("user", {}).get("login")
        if not author or author == pr["user"]["login"]:
            continue
        if review.get("commit_id") != expected.expected_head:
            continue
        permission = snapshot["reviewer_permissions"].get(author)
        if permission in WRITE_PERMISSIONS:
            approvals.append(author)
    checks.append(
        Check(
            "independent_approval",
            "PASS" if approvals else "BLOCKED",
            (
                f"Independent approval on fixed HEAD by: "
                f"{sorted(set(approvals))}."
                if approvals
                else "No independent write-capable reviewer approved the fixed HEAD."
            ),
        )
    )
    return checks


def collect_snapshot(
    client: GitHubClient,
    expected: Expectation,
) -> dict[str, Any]:
    owner, repo = expected.repository.split("/", maxsplit=1)
    root = f"/repos/{owner}/{repo}"
    pr = client.get(f"{root}/pulls/{expected.pr_number}")
    encoded_base = urllib.parse.quote(expected.expected_base_ref, safe="")
    base_ref = client.get(f"{root}/git/ref/heads/{encoded_base}")
    compare = client.get(
        f"{root}/compare/{expected.expected_base_sha}...{expected.expected_head}"
    )
    reviews = client.get(
        f"{root}/pulls/{expected.pr_number}/reviews",
        {"per_page": "100"},
    )
    runs = client.get(
        f"{root}/actions/runs",
        {
            "head_sha": expected.expected_head,
            "event": "pull_request",
            "per_page": "100",
        },
    )["workflow_runs"]

    graphql = client.graphql(
        """
        query($owner: String!, $repo: String!, $number: Int!) {
          repository(owner: $owner, name: $repo) {
            pullRequest(number: $number) {
              autoMergeRequest { enabledAt }
              reviewThreads(first: 100) {
                nodes { isResolved }
                pageInfo { hasNextPage }
              }
            }
          }
        }
        """,
        {"owner": owner, "repo": repo, "number": expected.pr_number},
    )["repository"]["pullRequest"]
    review_threads = graphql["reviewThreads"]
    if review_threads["pageInfo"]["hasNextPage"]:
        raise RuntimeError(
            "More than 100 review threads exist; pagination is required before approval."
        )

    reviewer_permissions: dict[str, str] = {}
    for review in reviews:
        login = review.get("user", {}).get("login")
        if (
            not login
            or login == pr["user"]["login"]
            or login in reviewer_permissions
        ):
            continue
        permission = client.get(f"{root}/collaborators/{login}/permission")[
            "permission"
        ]
        reviewer_permissions[login] = permission

    return {
        "pr": pr,
        "base_sha": base_ref["object"]["sha"],
        "compare": compare,
        "reviews": reviews,
        "workflow_runs": runs,
        "reviewer_permissions": reviewer_permissions,
        "unresolved_threads": sum(
            not node["isResolved"] for node in review_threads["nodes"]
        ),
        "auto_merge_enabled": graphql["autoMergeRequest"] is not None,
    }


def _split_csv(value: str) -> frozenset[str]:
    return frozenset(item.strip() for item in value.split(",") if item.strip())


def _write_result(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a fixed-head pull-request approval gate."
    )
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--expected-base-ref", default="master")
    parser.add_argument("--expected-base-sha", required=True)
    parser.add_argument("--expected-ahead", type=int, required=True)
    parser.add_argument("--expected-behind", type=int, default=0)
    parser.add_argument(
        "--expected-files",
        required=True,
        help="Comma-separated exact file paths.",
    )
    parser.add_argument(
        "--required-workflows",
        required=True,
        help="Comma-separated workflow names.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GH_TOKEN or GITHUB_TOKEN is required.")

    expected = Expectation(
        repository=args.repository,
        pr_number=args.pr_number,
        expected_head=args.expected_head,
        expected_base_ref=args.expected_base_ref,
        expected_base_sha=args.expected_base_sha,
        expected_ahead=args.expected_ahead,
        expected_behind=args.expected_behind,
        expected_files=_split_csv(args.expected_files),
        required_workflows=_split_csv(args.required_workflows),
    )
    try:
        client = GitHubClient(
            token,
            os.environ.get("GITHUB_API_URL", "https://api.github.com"),
        )
        snapshot = collect_snapshot(client, expected)
        checks = evaluate_snapshot(snapshot, expected)
        if all(check.status == "PASS" for check in checks):
            overall = "PASS"
        elif any(check.status == "FAIL" for check in checks):
            overall = "FAIL"
        else:
            overall = "BLOCKED"
        payload = {
            "schema_version": 1,
            "overall": overall,
            "checks": [check.__dict__ for check in checks],
        }
    except Exception as exc:
        payload = {
            "schema_version": 1,
            "overall": "INCONCLUSIVE",
            "error_type": type(exc).__name__,
            "message": str(exc),
        }

    _write_result(args.output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["overall"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
