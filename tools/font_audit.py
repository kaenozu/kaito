#!/usr/bin/env python3
"""
tools/font_audit.py
全 CTk ウィジェットのフォント実測値をダーク/ライト両テーマで一覧化する検査スクリプト

- アプリで実際に使うフォント（theme.font / theme.ui_font / theme.primary_button 等）で
  CTk ウィジェットを生成し、Tk に問い合わせた実測値（family / size / weight / metrics）を出力する
- テーマは外観にのみ影響し、フォント実測値は同一であるべきことを検証する
- あわせて ttk.Treeview（フォント指定タプル）の実測値を並べ、CTk 側と比較できるようにする

使い方:
    uv run python tools/font_audit.py             # 標準出力 + preview/font-audit.html
    uv run python tools/font_audit.py --no-html   # 標準出力のみ
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk
from typing import Callable

import customtkinter as ctk

from kaito.gui import theme

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPECTED_FAMILY = "Segoe UI"
REFERENCE_TEXT = "Aq screenshot (1).png"


# ---- 計測ヘルパー ----


def _parse_tcl_pairs(values) -> dict:
    """Tcl の '-key value' 列（list または空白区切り文字列）を dict に変換する"""
    if isinstance(values, str):
        parts = values.split()
    else:
        parts = list(values)
    return {parts[i]: parts[i + 1] for i in range(0, len(parts), 2)}


def _measure_named(root, name: str) -> dict:
    actual = _parse_tcl_pairs(root.tk.call("font", "actual", name))
    metrics = _parse_tcl_pairs(root.tk.call("font", "metrics", name))
    return {
        "family": actual["-family"],
        "size": actual["-size"],
        "weight": actual["-weight"],
        "ascent": metrics["-ascent"],
        "descent": metrics["-descent"],
        "linespace": metrics["-linespace"],
    }


def _measure_spec(root, spec) -> dict:
    """フォント指定タプル（例: ("Segoe UI", 9)）を実測する"""
    f = tkfont.Font(font=spec)
    name = str(f)
    m = _measure_named(root, name)
    f.__del__()
    return m


def _measure_widget_font(root, widget, option: str = "font") -> dict:
    return _measure_named(root, str(widget.cget(option)))


# ---- ウィジェット生成 ----


def _build_widgets(parent) -> list[tuple[str, str, Callable[[], dict]]]:
    """(表示名, フォント供給元, 計測関数) の一覧を生成する"""
    items: list[tuple[str, str, Callable[[], dict]]] = []
    root = parent.winfo_toplevel()

    def add(kind: str, source: str, get_font_name: Callable[[], str]) -> None:
        items.append((kind, source, lambda: _measure_named(root, get_font_name())))

    # CTkLabel（サイズラダー: アプリで使用する全サイズ）
    for size in (12, 13, 18, 22, 30):
        lbl = ctk.CTkLabel(
            parent, text="Aq", font=theme.font(size, "bold" if size >= 18 else "normal")
        )
        add(
            f"CTkLabel font({size})",
            f"theme.font({size})",
            lambda w=lbl: str(w.cget("font")),
        )

    # CTkLabel / CTkEntry（入力系は ui_font）
    lbl12 = ctk.CTkLabel(parent, text="Aq", font=theme.ui_font(12))
    add("CTkLabel ui_font(12)", "theme.ui_font(12)", lambda: str(lbl12.cget("font")))
    entry = ctk.CTkEntry(parent, placeholder_text="検索…", font=theme.ui_font(12))
    add("CTkEntry (検索ボックス)", "theme.ui_font(12)", lambda: str(entry.cget("font")))

    # ボタン（プライマリ/セカンダリ: theme ヘルパー経由）
    # アプリは bold を渡さない（デフォルト bold=False → weight は normal）
    btn_primary = theme.primary_button(parent, text="抽出", command=lambda: None)
    add(
        "CTkButton primary",
        "theme.primary_button (font(13))",
        lambda: str(btn_primary.cget("font")),
    )
    btn_secondary = theme.secondary_button(
        parent, text="キャンセル", command=lambda: None, is_dark=False
    )
    add(
        "CTkButton secondary",
        "theme.secondary_button (font(13))",
        lambda: str(btn_secondary.cget("font")),
    )

    # ドロップダウン（font + dropdown_font）
    om = theme.option_menu(
        parent, values=["a"], variable=ctk.StringVar(value="a"), is_dark=False
    )
    add("CTkOptionMenu", "theme.option_menu (font(13))", lambda: str(om.cget("font")))
    items.append(
        (
            "CTkOptionMenu.dropdown",
            "theme.option_menu (dropdown_font(13))",
            lambda: _measure_widget_font(root, om, "dropdown_font"),
        )
    )

    # その他のウィジェット種別
    cb = ctk.CTkCheckBox(parent, text="Aq", font=theme.font(13))
    add("CTkCheckBox", "theme.font(13)", lambda: str(cb.cget("font")))
    tb = ctk.CTkTextbox(parent, height=40, font=theme.ui_font(12))
    add("CTkTextbox", "theme.ui_font(12)", lambda: str(tb.cget("font")))
    combo = ctk.CTkComboBox(
        parent, values=["a"], font=theme.font(13), dropdown_font=theme.font(13)
    )
    add("CTkComboBox", "theme.font(13)", lambda: str(combo.cget("font")))
    items.append(
        (
            "CTkComboBox.dropdown",
            "theme.font(13) (dropdown_font)",
            lambda: _measure_widget_font(root, combo, "dropdown_font"),
        )
    )
    seg = ctk.CTkSegmentedButton(parent, values=["a"], font=theme.font(13))
    add("CTkSegmentedButton", "theme.font(13)", lambda: str(seg.cget("font")))

    # ttk.Treeview（タプル指定: 入力系との比較用）
    style = ttk.Style(parent)
    style.theme_use("clam")
    style.configure("Treeview", font=(theme.TREE_FONT_FAMILY, theme.TREE_FONT_SIZE))
    style.configure(
        "Treeview.Heading", font=(theme.TREE_FONT_FAMILY, theme.TREE_FONT_SIZE, "bold")
    )
    items.append(
        (
            "ttk.Treeview 行",
            "(TREE_FONT_FAMILY, TREE_FONT_SIZE)",
            lambda: _measure_spec(root, (theme.TREE_FONT_FAMILY, theme.TREE_FONT_SIZE)),
        )
    )
    items.append(
        (
            "ttk.Treeview 見出し",
            "(TREE_FONT_FAMILY, TREE_FONT_SIZE, bold)",
            lambda: _measure_spec(
                root, (theme.TREE_FONT_FAMILY, theme.TREE_FONT_SIZE, "bold")
            ),
        )
    )
    return items


# ---- 出力 ----


def _format_table(rows: list[tuple[str, str, dict]]) -> str:
    header = (
        "ウィジェット",
        "フォント供給元",
        "family",
        "size",
        "weight",
        "asc",
        "desc",
        "linespace",
    )
    data = [
        (
            kind,
            source,
            m["family"],
            str(m["size"]),
            m["weight"],
            str(m["ascent"]),
            str(m["descent"]),
            str(m["linespace"]),
        )
        for kind, source, m in rows
    ]
    widths = [
        max(len(header[i]), *(len(r[i]) for r in data)) for i in range(len(header))
    ]
    lines = [" | ".join(h.ljust(widths[i]) for i, h in enumerate(header))]
    lines.append("-+-".join("-" * widths[i] for i in range(len(header))))
    for r in data:
        lines.append(" | ".join(r[i].ljust(widths[i]) for i in range(len(header))))
    return "\n".join(lines)


def _render_html(theme_results: dict[str, list[tuple[str, str, dict]]]) -> str:
    table_rows = ""
    for mode in ("light", "dark"):
        table_rows += (
            f'<tr><td colspan="8" style="background:#eef1f7;font-weight:700">'
            f"テーマ: {mode}</td></tr>"
        )
        for kind, source, m in theme_results[mode]:
            table_rows += (
                f"<tr><td>{kind}</td><td>{source}</td><td>{m['family']}</td>"
                f"<td>{m['size']}</td><td>{m['weight']}</td><td>{m['ascent']}</td>"
                f"<td>{m['descent']}</td><td>{m['linespace']}</td></tr>"
            )
    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<title>kaito フォント実測値監査（ダーク/ライト）</title>
<style>
  body {{ background:#f3f5fa; color:#16181d; font-family:"Segoe UI","Yu Gothic UI",sans-serif; padding:20px; }}
  h1 {{ font-size:16px; }} p {{ font-size:12px; color:#677085; }}
  table {{ border-collapse:collapse; font-size:12px; }}
  th,td {{ border:1px solid #e2e6ef; padding:4px 10px; text-align:left; }}
  th {{ background:#f8f9fc; }}
  .ng {{ color:#c0392b; font-weight:700; }}
</style></head><body>
<h1>kaito フォント実測値（全 CTk ウィジェット・両テーマ）</h1>
<p>実測は Tk への問い合わせ（font actual / font metrics）。size は Tk 単位
（CTkFont はポイント由来、ツリーのタプルはピクセル指定）。テーマ間で値が
一致していることが正常（テーマはフォントに影響しない）。</p>
<table>
<tr><th>ウィジェット</th><th>フォント供給元</th><th>family</th><th>size</th>
<th>weight</th><th>ascent</th><th>descent</th><th>linespace</th></tr>
{table_rows}
</table>
</body></html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="kaito フォント実測値の検査スクリプト")
    parser.add_argument(
        "--no-html", action="store_true", help="HTML レポートを書き出さない"
    )
    args = parser.parse_args()

    root = ctk.CTk()
    root.withdraw()
    root.update()

    theme_results: dict[str, list[tuple[str, str, dict]]] = {}
    failures: list[str] = []
    for mode in ("light", "dark"):
        ctk.set_appearance_mode(mode)
        holder = ctk.CTkFrame(root)
        holder.update()
        rows = []
        for kind, source, measure in _build_widgets(holder):
            m = measure()
            rows.append((kind, source, m))
            if m["family"] != EXPECTED_FAMILY:
                failures.append(f"[{mode}] {kind}: family={m['family']}")
        holder.destroy()
        root.update()
        theme_results[mode] = rows

    # テーマ不変性チェック（フォントはテーマに依存しないはず）
    invariance_ok = all(
        (r1[0], r1[2]["family"], r1[2]["size"], r1[2]["weight"], r1[2]["linespace"])
        == (r2[0], r2[2]["family"], r2[2]["size"], r2[2]["weight"], r2[2]["linespace"])
        for r1, r2 in zip(theme_results["light"], theme_results["dark"])
    )

    print("== ライトテーマ ==")
    print(_format_table(theme_results["light"]))
    print()
    print("== ダークテーマ ==")
    print(_format_table(theme_results["dark"]))
    print()
    print(
        f"テーマ不変性（両テーマでフォント実測値が同一）: {'OK' if invariance_ok else 'NG'}"
    )
    if failures:
        print("想定外の family が検出されました:")
        for f in failures:
            print(f"  {f}")
    else:
        print(f"全ウィジェットの family が {EXPECTED_FAMILY}: OK")

    root.destroy()

    if not args.no_html:
        out = REPO_ROOT / "preview" / "font-audit.html"
        out.write_text(_render_html(theme_results), encoding="utf-8")
        print(f"HTML レポート: {out}")

    return 1 if failures or not invariance_ok else 0


if __name__ == "__main__":
    sys.exit(main())
