"""
tools/check_mock_theme.py
preview/index.html の CSS 変数と src/kaito/gui/theme.py のビジュアルトークンの突合検査。

theme.py の各色トークン（ライト/ダークのタプル、または単一色）がモックの CSS 変数と
両テーマで一致しているかを機械的に検証する。不一致・未定義の CSS 変数参照・
theme.py に追加された未対応トークンがある場合は exit 1。

モックの CSS 変数は「アプリのトークンの写し」であるべきで、手で書き換えても
この検査が乖離を検知する。単一ソースは theme.py 側。

使い方:
    uv run python tools/check_mock_theme.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from kaito.gui import theme

# CI（windows-latest）のコンソールは cp1252/cp932 のため、日本語出力で UnicodeEncodeError に
# ならないよう stdout/stderr を UTF-8 に再構成する。ローカル実行にも影響はない。
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure is not None:
        try:
            _reconfigure(encoding="utf-8", errors="replace")
        except ValueError:
            pass

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "preview" / "index.html"

# (theme.py のトークン指定, CSS 変数名)
# トークン指定は単一名（BG のように (light, dark) タプル値）か
# ペア（TREE_LIGHT_FG, TREE_DARK_FG のように別名の2トークン）。
MAPPINGS: list[tuple[str | tuple[str, str], str]] = [
    ("ACCENT", "--accent"),
    ("ACCENT_HOVER", "--accent-hover"),
    ("BG", "--bg"),
    ("SURFACE", "--panel"),
    ("SURFACE_2", "--panel-2"),
    ("BORDER", "--border"),
    ("TEXT", "--text"),
    ("SUBTEXT", "--muted"),
    ("ACCENT_SOFT", "--accent-soft"),
    ("DROP_BORDER", "--drop-border"),
    ("DROP_HIGHLIGHT", "--drop-hl"),
    ("TEXT_ERROR", "--err"),
    ("TEXT_SUCCESS", "--ok"),
    ("TEXT_WARN", "--warn"),
    (("TREE_LIGHT_BG", "TREE_DARK_BG"), "--panel"),  # ツリー背景はカード面と同じ色
    (("TREE_LIGHT_FG", "TREE_DARK_FG"), "--tree-fg"),
    (("TREE_LIGHT_HEADER", "TREE_DARK_HEADER"), "--tree-head-bg"),
    (("TREE_LIGHT_HEADER_ACTIVE", "TREE_DARK_HEADER_ACTIVE"), "--tree-head-active"),
    (("TREE_LIGHT_SELECT_BG", "TREE_DARK_SELECT_BG"), "--tree-sel-bg"),
    (("TREE_LIGHT_SELECT_FG", "TREE_DARK_SELECT_FG"), "--tree-sel-fg"),
]

# CSS 変数として意図的に持たないトークン（理由付き。モックで再現しない）
NOT_IN_CSS: dict[str, str] = {
    "ACCENT_ON": "プライマリボタンの文字色。モックは #fff リテラルで表現",
    "TREE_ROW_HEIGHT": "数値定数。モックは行の padding で表現",
}


def _expected(spec: str | tuple[str, str]) -> tuple[str, str]:
    """トークン指定 → (ライト値, ダーク値)"""
    if isinstance(spec, tuple):
        return getattr(theme, spec[0]), getattr(theme, spec[1])
    val = getattr(theme, spec)
    if isinstance(val, tuple):
        return val[0], val[1]
    return val, val


def _color_tokens() -> dict[str, tuple[str, str]]:
    """theme.py の色トークンを自動収集（未対応トークンの検出用）"""
    found: dict[str, tuple[str, str]] = {}
    for name in dir(theme):
        if not name.isupper() or name.startswith("_"):
            continue
        val = getattr(theme, name)
        if (
            isinstance(val, tuple)
            and len(val) == 2
            and all(isinstance(v, str) and v.startswith("#") for v in val)
        ):
            found[name] = (val[0], val[1])
        elif isinstance(val, str) and val.startswith("#"):
            found[name] = (val, val)
    return found


def _css_blocks(html: str) -> dict[str, str]:
    """index.html から :root / dark の CSS 変数ブロックを抽出"""
    root = re.search(r":root\s*\{([^}]*)\}", html)
    dark = re.search(r'html\[data-theme="dark"\]\s*\{([^}]*)\}', html)
    if root is None or dark is None:
        raise SystemExit(
            "error: index.html に :root / html[data-theme=dark] ブロックが見つかりません"
        )
    return {"light": root.group(1), "dark": dark.group(1)}


def _var_value(block: str, var: str) -> str | None:
    m = re.search(rf"{re.escape(var)}\s*:\s*([^;]+);", block)
    return m.group(1).strip() if m else None


def _referenced_vars(css: str) -> set[str]:
    return set(re.findall(r"var\((--[a-z0-9-]+)", css))


def main() -> int:
    html = INDEX.read_text(encoding="utf-8")
    blocks = _css_blocks(html)
    root_css = blocks["light"] + blocks["dark"]

    failures: list[str] = []
    rows: list[tuple[str, str, str, str, bool]] = []

    for spec, var in MAPPINGS:
        exp_light, exp_dark = _expected(spec)
        css_light = _var_value(blocks["light"], var)
        css_dark = _var_value(blocks["dark"], var)

        def norm(s: str) -> str:
            return s.lower()

        light_ok = css_light is not None and norm(css_light) == norm(exp_light)
        if exp_light == exp_dark:
            # 単一色トークン: dark ブロックで再定義されていなければ :root を継承（OK）
            dark_ok = css_dark is None or norm(css_dark) == norm(exp_dark)
        else:
            dark_ok = css_dark is not None and norm(css_dark) == norm(exp_dark)
        ok = light_ok and dark_ok
        rows.append((f"{spec} -> {var}", exp_light, exp_dark, "", ok))
        if not ok:
            failures.append(
                f"  {spec} -> {var}: 期待 light={exp_light} dark={exp_dark}, "
                f"CSS light={css_light or '未定義'} dark={css_dark or '未定義(継承)'}"
            )

    # 未定義 CSS 変数の参照チェック
    defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", root_css))
    for var in sorted(_referenced_vars(html) - defined):
        failures.append(f"  var({var}) が参照されているが :root に定義がない")

    # theme.py に追加された未対応トークンの検出
    mapped: set[str] = set()
    for spec, _var in MAPPINGS:
        mapped.update(spec) if isinstance(spec, tuple) else mapped.add(spec)
    for name, (light, dark) in sorted(_color_tokens().items()):
        if name in mapped or name in NOT_IN_CSS:
            continue
        failures.append(
            f"  theme.py の新トークン {name} ({light}/{dark}) が MAPPINGS / NOT_IN_CSS に未登録"
        )

    # 出力
    width = max(len(r[0]) for r in rows) + 2
    print("theme.py token -> CSS var の突合:")
    for label, exp_light, exp_dark, _extra, ok in rows:
        print(
            f"  {label:<{width}} light={exp_light:<8} dark={exp_dark:<8} {'OK' if ok else 'NG'}"
        )
    for name, reason in sorted(NOT_IN_CSS.items()):
        print(f"  (info) {name}: CSS には持たない — {reason}")

    if failures:
        print("\nNG:")
        for f in failures:
            print(f)
        return 1
    print("\nOK: 全トークンがモックの CSS 変数と一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
