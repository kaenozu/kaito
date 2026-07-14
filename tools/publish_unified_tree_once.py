from __future__ import annotations

import base64
import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPOSITORY = os.environ["GITHUB_REPOSITORY"]
BRANCH = "agent/unified-review-release-fixes"
TOKEN = os.environ["GITHUB_TOKEN"]
API_ROOT = os.environ.get("GITHUB_API_URL", "https://api.github.com")
ROOT = Path(__file__).resolve().parents[1]
TEMPORARY_PATHS = {
    ".github/workflows/unified-finalizer.yml",
    "tools/apply_unified_fixes_once.py",
    "tools/publish_unified_tree_once.py",
}


def api(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{API_ROOT}/repos/{REPOSITORY}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "kaito-unified-finalizer",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content = response.read()
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {method} {path} failed: {exc.code}: {details}") from exc
    return json.loads(content) if content else None


def git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def changed_paths() -> tuple[set[str], set[str]]:
    modified = {
        line.strip()
        for line in git("diff", "--name-only", "--diff-filter=ACMRT", "HEAD").splitlines()
        if line.strip()
    }
    modified.update(
        line.strip()
        for line in git("ls-files", "--others", "--exclude-standard").splitlines()
        if line.strip()
    )
    deleted = {
        line.strip()
        for line in git("diff", "--name-only", "--diff-filter=D", "HEAD").splitlines()
        if line.strip()
    }
    deleted.update(TEMPORARY_PATHS)
    modified.difference_update(TEMPORARY_PATHS)
    return modified, deleted


def main() -> None:
    local_head = git("rev-parse", "HEAD")
    ref = api("GET", f"/git/ref/heads/{BRANCH}")
    remote_head = str(ref["object"]["sha"])
    if local_head != remote_head:
        raise RuntimeError(
            f"Branch advanced during finalization: local={local_head} remote={remote_head}"
        )

    commit = api("GET", f"/git/commits/{remote_head}")
    base_tree = str(commit["tree"]["sha"])
    modified, deleted = changed_paths()
    if not modified and not deleted:
        raise RuntimeError("Unified finalizer produced no tree changes.")

    elements: list[dict[str, Any]] = []
    for relative in sorted(modified):
        data = (ROOT / relative).read_bytes()
        blob = api(
            "POST",
            "/git/blobs",
            {
                "content": base64.b64encode(data).decode("ascii"),
                "encoding": "base64",
            },
        )
        elements.append(
            {"path": relative, "mode": "100644", "type": "blob", "sha": blob["sha"]}
        )

    for relative in sorted(deleted):
        elements.append(
            {"path": relative, "mode": "100644", "type": "blob", "sha": None}
        )

    tree = api("POST", "/git/trees", {"base_tree": base_tree, "tree": elements})
    new_commit = api(
        "POST",
        "/git/commits",
        {
            "message": "refactor: unify release governance and application fixes",
            "tree": tree["sha"],
            "parents": [remote_head],
        },
    )
    api(
        "PATCH",
        f"/git/refs/heads/{BRANCH}",
        {"sha": new_commit["sha"], "force": False},
    )
    print(f"Published unified commit {new_commit['sha']}")


if __name__ == "__main__":
    main()
