"""
tools/check_all.py
make なしで Makefile の check ターゲットと同一の検査を順に実行する。

make check と同じ 4 検査を subprocess で実行する（Makefile のターゲットと対応）:
    check-mock-i18n   tools/gen_mock_i18n.py --check
    check-mock-theme  tools/check_mock_theme.py
    check-mock-render tools/check_mock_render.py --no-html
    check-font-audit  tools/font_audit.py --no-html

make と同様、失敗した時点で停止する（--keep-going で最後まで実行）。
exit code: 全成功で 0、いずれか失敗で 1、使い方エラーで 2。

使い方:
    uv run python tools/check_all.py              # 全検査
    uv run python tools/check_all.py --list       # 対象の一覧
    uv run python tools/check_all.py --only check-mock-i18n,check-mock-theme
    uv run python tools/check_all.py --keep-going # 失敗しても続行
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# CI（windows-latest）のコンソールは cp1252/cp932 のため、日本語出力で UnicodeEncodeError に
# ならないよう stdout/stderr を UTF-8 に再構成する。ローカル実行にも影響はない。
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure is not None:
        try:
            _reconfigure(encoding="utf-8", errors="replace")
        except ValueError:
            pass

# (検査名, スクリプトの相対パス, 追加引数) — Makefile の各ターゲットと対応
CHECKS: list[tuple[str, str, list[str]]] = [
    ("check-mock-i18n", "tools/gen_mock_i18n.py", ["--check"]),
    ("check-mock-theme", "tools/check_mock_theme.py", []),
    ("check-mock-render", "tools/check_mock_render.py", ["--no-html"]),
    ("check-font-audit", "tools/font_audit.py", ["--no-html"]),
]


def _kaito_importable() -> bool:
    """subprocess 側でも kaito を import できるか（親と同じ venv を使うため親で確認）"""
    return importlib.util.find_spec("kaito") is not None


def _run_one(name: str, script: str, extra: list[str]) -> tuple[int, float]:
    """1 検査を subprocess で実行し、出力をそのまま表示して (exit code, 所要秒) を返す"""
    cmd = [sys.executable, str(ROOT / script), *extra]
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:  # pragma: no cover - スクリプト欠落等
        print(f"  error: {cmd[0]} を起動できません: {exc}", file=sys.stderr)
        return 127, time.perf_counter() - started
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, file=sys.stderr, end="")
    return proc.returncode, time.perf_counter() - started


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="検査の一覧を表示")
    parser.add_argument(
        "--only",
        metavar="NAME[,NAME...]",
        help="指定した検査だけ実行（例: check-mock-i18n,check-mock-theme）",
    )
    parser.add_argument(
        "--keep-going",
        "-k",
        action="store_true",
        help="失敗しても次の検査を続行（既定は make と同じく最初の失敗で停止）",
    )
    args = parser.parse_args()

    names = [name for name, _s, _a in CHECKS]
    if args.list:
        print("check_all で実行できる検査:")
        for name, script, extra in CHECKS:
            cmd = " ".join(["uv run", "python", script, *extra]).rstrip()
            print(f"  {name:<20} {cmd}")
        return 0

    if args.only:
        wanted = {n.strip() for n in args.only.split(",") if n.strip()}
        unknown = wanted - set(names)
        if unknown:
            print(f"error: 不明な検査名: {', '.join(sorted(unknown))}", file=sys.stderr)
            print(f"利用可能: {', '.join(names)}", file=sys.stderr)
            return 2
        selected = [c for c in CHECKS if c[0] in wanted]
    else:
        selected = CHECKS

    if not _kaito_importable():
        print(
            "error: kaito パッケージを import できません。"
            "`uv run python tools/check_all.py` のように uv 経由で実行してください。",
            file=sys.stderr,
        )
        return 2

    failed: list[str] = []
    results: list[tuple[str, int, float]] = []  # (検査名, exit code, 所要秒)
    total = len(selected)
    for i, (name, script, extra) in enumerate(selected, 1):
        print(f"\n--- [{i}/{total}] {name}: {script} {' '.join(extra)} ---")
        code, elapsed = _run_one(name, script, extra)
        results.append((name, code, elapsed))
        if code != 0:
            failed.append(name)
            print(f"!! {name} が失敗しました (exit {code}, {elapsed:.1f}s)")
            if not args.keep_going:
                break

    # 結果サマリー（実行した検査の 結果 / 所要時間）
    print("\n== 結果サマリー ==")
    width = max(len(name) for name, _c, _e in results)
    for name, code, elapsed in results:
        status = "OK" if code == 0 else f"NG(exit {code})"
        print(f"  {name:<{width}}  {status:<10} {elapsed:.1f}s")
    total_sec = sum(elapsed for _n, _c, elapsed in results)

    if failed:
        print(f"\nNG: 失敗した検査: {', '.join(failed)}（合計 {total_sec:.1f}s）")
        return 1
    print(f"\nOK: 全 {total} 検査が成功しました（合計 {total_sec:.1f}s）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
