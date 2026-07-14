from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "unified-tree"
FILES_ROOT = OUTPUT / "files"
TEMPORARY_PATHS = {
    ".github/workflows/unified-finalizer.yml",
    "tools/apply_unified_fixes_once.py",
    "tools/export_unified_tree_once.py",
    "tools/publish_unified_tree_once.py",
}


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


def lines(*args: str) -> set[str]:
    return {line.strip() for line in git(*args).splitlines() if line.strip()}


def main() -> None:
    modified = lines("diff", "--name-only", "--diff-filter=ACMRT", "HEAD")
    modified.update(lines("ls-files", "--others", "--exclude-standard"))
    deleted = lines("diff", "--name-only", "--diff-filter=D", "HEAD")
    deleted.update(TEMPORARY_PATHS)
    modified.difference_update(TEMPORARY_PATHS)
    modified = {path for path in modified if not path.startswith("artifacts/")}

    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    FILES_ROOT.mkdir(parents=True)

    for relative in sorted(modified):
        source = ROOT / relative
        if not source.is_file():
            raise RuntimeError(f"Expected validated file is missing: {relative}")
        target = FILES_ROOT / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    manifest = {
        "base_commit": git("rev-parse", "HEAD"),
        "modified": sorted(modified),
        "deleted": sorted(deleted),
    }
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
