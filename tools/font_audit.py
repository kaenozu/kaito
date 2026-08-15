#!/usr/bin/env python3
"""
tools/font_audit.py
全 CTk ウィジェットのフォント実測値をダーク/ライト両テーマで一覧化する検査スクリプト

- アプリで実際に使うフォント（theme.font / theme.ui_font / theme.primary_button 等）で
  CTk ウィジェットを生成し、Tk に問い合わせた実測値（family / size / weight / metrics）を出力する
- さらに、各フォントを白背景ラベルに描画してスクリーンショット解析し、
  実描画インク高（px）を実測して Tk 値との対応表を出力する
- テーマは外観にのみ影響し、フォント実測値は同一であるべきことを検証する
- あわせて ttk.Treeview（フォント指定タプル）の実測値を並べ、CTk 側と比較できるようにする

使い方:
    uv run python tools/font_audit.py             # 標準出力 + preview/font-audit.html
    uv run python tools/font_audit.py --no-html   # 標準出力のみ
    uv run python tools/font_audit.py --skip-ink  # 実インク高の計測をスキップ（Tk 値のみ）

実インク高の計測は ImageGrab による画面キャプチャのため、利用できない環境
（ヘッドレス等）では N/A となり Tk 値のみの検証に自動的に降格する。
exit code は family / テーマ不変性の検証結果に基づく（実インク高は参考値）。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk
from typing import Callable

import customtkinter as ctk
from PIL import ImageGrab

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

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPECTED_FAMILY = "Segoe UI"
REFERENCE_TEXT = "Aq screenshot (1).png"

_FontSpec = tkfont.Font | tuple[str, int] | tuple[str, int, str]


def _ink_specs() -> list[tuple[str, _FontSpec]]:
    """実インク高の計測対象（Tk ルート生成後に呼び出す。キーは _build_widgets の font_key と対応）"""
    return [
        ("font12", theme.font(12)),
        ("font13", theme.font(13)),
        ("font18b", theme.font(18, "bold")),
        ("font22b", theme.font(22, "bold")),
        ("font30b", theme.font(30, "bold")),
        ("ui12", theme.ui_font(12)),
        ("tree_row", (theme.TREE_FONT_FAMILY, theme.TREE_FONT_SIZE)),
        ("tree_heading", (theme.TREE_FONT_FAMILY, theme.TREE_FONT_SIZE, "bold")),
    ]


# ---- Tk 値の計測ヘルパー ----


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
    m = _measure_named(root, str(f))
    f.__del__()
    return m


def _measure_widget_font(root, widget, option: str = "font") -> dict:
    return _measure_named(root, str(widget.cget(option)))


# ---- 実インク高の計測（スクリーンショット解析） ----


def _ink_height_in_rect(img, rx: int, ry: int, rw: int, rh: int) -> int | None:
    """画像内の矩形（rx, ry, rw, rh）に描画された文字のインク高（px）を返す"""
    if rw < 8 or rh < 8 or rx < 0 or ry < 0:
        return None
    if rx + rw > img.width or ry + rh > img.height:
        return None
    # 境界（上下 2px）を除外して行ごとの暗い画素数を数える
    rows = [
        sum(1 for xx in range(2, rw - 2) if img.getpixel((rx + xx, ry + yy)) < 128)
        for yy in range(2, rh - 2)
    ]
    heights: list[int] = []
    start = None
    for i, n in enumerate(rows):
        if n > 0:
            if start is None:
                start = i
        elif start is not None:
            if i - start >= 2:
                heights.append(i - start)
            start = None
    if start is not None:
        heights.append(len(rows) - start)
    return max(heights) if heights else None


def _measure_ink_pass(root) -> dict[str, int | None]:
    """各フォントを白背景ラベルに描画し、実インク高を実測する

    画面キャプチャを使うため、計測ウィンドウを最前面（-topmost）に置く。
    キャプチャが他ウィンドウに隠れて真っ黒になる場合は N/A としてスキップする。
    """
    import tkinter as tk

    root.geometry("900x320")
    root.attributes("-topmost", True)
    holder = ctk.CTkFrame(root, fg_color="#ffffff", corner_radius=0)
    holder.pack(fill="both", expand=True, padx=10, pady=10)
    labels: list[tuple[str, tk.Label]] = []
    for key, spec in _ink_specs():
        lbl = tk.Label(
            holder, text=REFERENCE_TEXT, font=spec, bg="#ffffff", fg="#16181d"
        )
        lbl.pack(anchor="w", padx=10, pady=2)
        labels.append((key, lbl))

    root.update()
    time.sleep(0.4)
    root.update()
    ox, oy = root.winfo_rootx(), root.winfo_rooty()
    try:
        img = ImageGrab.grab(
            bbox=(ox, oy, ox + root.winfo_width(), oy + root.winfo_height())
        ).convert("L")
    except Exception as exc:  # pragma: no cover - ヘッドレス/権限なし等
        print(f"  (実インク高の計測をスキップ: {exc})")
        return {}
    # 他ウィンドウに隠れて真っ黒/単色になっていないか確認（画素の最小・最大が近い場合は異常）
    lo, hi = img.getextrema()
    if not isinstance(lo, (int, float)) or not isinstance(
        hi, (int, float)
    ):  # pragma: no cover
        print("  (実インク高の計測をスキップ: キャプチャ形式が想定外です)")
        return {}
    if hi - lo < 40:  # pragma: no cover - キャプチャ不可環境
        print("  (実インク高の計測をスキップ: キャプチャが単色で内容を検出できません)")
        return {}
    result: dict[str, int | None] = {}
    for key, lbl in labels:
        result[key] = _ink_height_in_rect(
            img,
            lbl.winfo_rootx() - ox,
            lbl.winfo_rooty() - oy,
            lbl.winfo_width(),
            lbl.winfo_height(),
        )
    holder.destroy()
    root.update()
    return result


# ---- ウィジェット生成 ----


def _build_widgets(parent) -> list[tuple[str, str, str, Callable[[], dict]]]:
    """(表示名, フォント供給元, font_key, 計測関数) の一覧を生成する"""
    items: list[tuple[str, str, str, Callable[[], dict]]] = []
    root = parent.winfo_toplevel()

    def add(
        kind: str, source: str, font_key: str, get_font_name: Callable[[], str]
    ) -> None:
        items.append(
            (kind, source, font_key, lambda: _measure_named(root, get_font_name()))
        )

    # CTkLabel（サイズラダー: アプリで使用する全サイズ）
    for size, key in (
        (12, "font12"),
        (13, "font13"),
        (18, "font18b"),
        (22, "font22b"),
        (30, "font30b"),
    ):
        lbl = ctk.CTkLabel(
            parent, text="Aq", font=theme.font(size, "bold" if size >= 18 else "normal")
        )
        add(
            f"CTkLabel font({size})",
            f"theme.font({size})",
            key,
            lambda w=lbl: str(w.cget("font")),
        )

    # CTkLabel / CTkEntry（入力系は ui_font）
    lbl12 = ctk.CTkLabel(parent, text="Aq", font=theme.ui_font(12))
    add(
        "CTkLabel ui_font(12)",
        "theme.ui_font(12)",
        "ui12",
        lambda: str(lbl12.cget("font")),
    )
    entry = ctk.CTkEntry(parent, placeholder_text="検索…", font=theme.ui_font(12))
    add(
        "CTkEntry (検索ボックス)",
        "theme.ui_font(12)",
        "ui12",
        lambda: str(entry.cget("font")),
    )

    # ボタン（プライマリ/セカンダリ: theme ヘルパー経由）
    # プライマリは既定 bold=True（セカンダリは normal）
    btn_primary = theme.primary_button(parent, text="抽出", command=lambda: None)
    add(
        "CTkButton primary",
        "theme.primary_button (font(13,bold))",
        "font13",
        lambda: str(btn_primary.cget("font")),
    )
    btn_secondary = theme.secondary_button(
        parent, text="キャンセル", command=lambda: None, is_dark=False
    )
    add(
        "CTkButton secondary",
        "theme.secondary_button (font(13))",
        "font13",
        lambda: str(btn_secondary.cget("font")),
    )

    # ドロップダウン（font + dropdown_font）
    om = theme.option_menu(
        parent, values=["a"], variable=ctk.StringVar(value="a"), is_dark=False
    )
    add(
        "CTkOptionMenu",
        "theme.option_menu (font(13))",
        "font13",
        lambda: str(om.cget("font")),
    )
    items.append(
        (
            "CTkOptionMenu.dropdown",
            "theme.option_menu (dropdown_font(13))",
            "font13",
            lambda: _measure_widget_font(root, om, "dropdown_font"),
        )
    )

    # その他のウィジェット種別
    cb = ctk.CTkCheckBox(parent, text="Aq", font=theme.font(13))
    add("CTkCheckBox", "theme.font(13)", "font13", lambda: str(cb.cget("font")))
    tb = ctk.CTkTextbox(parent, height=40, font=theme.ui_font(12))
    add("CTkTextbox", "theme.ui_font(12)", "ui12", lambda: str(tb.cget("font")))
    combo = ctk.CTkComboBox(
        parent, values=["a"], font=theme.font(13), dropdown_font=theme.font(13)
    )
    add("CTkComboBox", "theme.font(13)", "font13", lambda: str(combo.cget("font")))
    items.append(
        (
            "CTkComboBox.dropdown",
            "theme.font(13) (dropdown_font)",
            "font13",
            lambda: _measure_widget_font(root, combo, "dropdown_font"),
        )
    )
    seg = ctk.CTkSegmentedButton(parent, values=["a"], font=theme.font(13))
    add("CTkSegmentedButton", "theme.font(13)", "font13", lambda: str(seg.cget("font")))

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
            "tree_row",
            lambda: _measure_spec(root, (theme.TREE_FONT_FAMILY, theme.TREE_FONT_SIZE)),
        )
    )
    items.append(
        (
            "ttk.Treeview 見出し",
            "(TREE_FONT_FAMILY, TREE_FONT_SIZE, bold)",
            "tree_heading",
            lambda: _measure_spec(
                root, (theme.TREE_FONT_FAMILY, theme.TREE_FONT_SIZE, "bold")
            ),
        )
    )
    return items


# ---- 出力 ----


def _format_table(
    rows: list[tuple[str, str, str, dict]], inks: dict[str, int | None]
) -> str:
    header = (
        "ウィジェット",
        "フォント供給元",
        "family",
        "size",
        "weight",
        "asc",
        "desc",
        "linespace",
        "実インク(px)",
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
            str(inks.get(font_key)) if inks.get(font_key) is not None else "N/A",
        )
        for kind, source, font_key, m in rows
    ]
    widths = [
        max(len(header[i]), *(len(r[i]) for r in data)) for i in range(len(header))
    ]
    lines = [" | ".join(h.ljust(widths[i]) for i, h in enumerate(header))]
    lines.append("-+-".join("-" * widths[i] for i in range(len(header))))
    for r in data:
        lines.append(" | ".join(r[i].ljust(widths[i]) for i in range(len(header))))
    return "\n".join(lines)


def _render_html(
    theme_results: dict[str, list[tuple[str, str, str, dict]]],
    inks: dict[str, int | None],
) -> str:
    table_rows = ""
    for mode in ("light", "dark"):
        table_rows += (
            f'<tr><td colspan="9" style="background:#eef1f7;font-weight:700">'
            f"テーマ: {mode}</td></tr>"
        )
        for kind, source, font_key, m in theme_results[mode]:
            ink = inks.get(font_key)
            ink_td = str(ink) if ink is not None else "N/A"
            table_rows += (
                f"<tr><td>{kind}</td><td>{source}</td><td>{m['family']}</td>"
                f"<td>{m['size']}</td><td>{m['weight']}</td><td>{m['ascent']}</td>"
                f"<td>{m['descent']}</td><td>{m['linespace']}</td><td>{ink_td}</td></tr>"
            )
    ink_note = (
        "実インク高は白背景ラベルへの実描画をスクリーンショット解析した値（px）。"
        "環境で計測できない場合は N/A となる。"
        if inks
        else "実インク高はこの環境では計測できませんでした（N/A）。"
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
<p>実測は Tk への問い合わせ（font actual / font metrics）と実描画のスクリーンショット解析。
size は Tk 単位（CTkFont はポイント由来、ツリーのタプルはピクセル指定）。
{ink_note} テーマ間で値が一致していることが正常（テーマはフォントに影響しない）。</p>
<table>
<tr><th>ウィジェット</th><th>フォント供給元</th><th>family</th><th>size</th>
<th>weight</th><th>ascent</th><th>descent</th><th>linespace</th><th>実インク(px)</th></tr>
{table_rows}
</table>
</body></html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="kaito フォント実測値の検査スクリプト")
    parser.add_argument(
        "--no-html", action="store_true", help="HTML レポートを書き出さない"
    )
    parser.add_argument(
        "--skip-ink", action="store_true", help="実インク高の計測をスキップする"
    )
    args = parser.parse_args()

    root = ctk.CTk()
    root.update()

    # 実インク高の計測（ウィンドウ表示が必要なため withdraw 前に実施）
    inks: dict[str, int | None] = {} if args.skip_ink else _measure_ink_pass(root)

    root.withdraw()
    root.update()

    theme_results: dict[str, list[tuple[str, str, str, dict]]] = {}
    failures: list[str] = []
    for mode in ("light", "dark"):
        ctk.set_appearance_mode(mode)
        holder = ctk.CTkFrame(root)
        holder.update()
        rows = []
        for kind, source, font_key, measure in _build_widgets(holder):
            m = measure()
            rows.append((kind, source, font_key, m))
            if m["family"] != EXPECTED_FAMILY:
                failures.append(f"[{mode}] {kind}: family={m['family']}")
        holder.destroy()
        root.update()
        theme_results[mode] = rows

    # テーマ不変性チェック（フォントはテーマに依存しないはず）
    invariance_ok = all(
        (r1[0], r1[3]["family"], r1[3]["size"], r1[3]["weight"], r1[3]["linespace"])
        == (r2[0], r2[3]["family"], r2[3]["size"], r2[3]["weight"], r2[3]["linespace"])
        for r1, r2 in zip(theme_results["light"], theme_results["dark"])
    )

    print("== ライトテーマ ==")
    print(_format_table(theme_results["light"], inks))
    print()
    print("== ダークテーマ ==")
    print(_format_table(theme_results["dark"], inks))
    print()
    if inks:
        print("== 実インク高（白背景・ライトテーマでの実描画） ==")
        for key, _spec in _ink_specs():
            v = inks.get(key)
            print(f"  {key:<12} 実インク = {v if v is not None else 'N/A'}px")
    else:
        print("実インク高: この環境では計測できませんでした（N/A）")
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
        out.write_text(_render_html(theme_results, inks), encoding="utf-8")
        print(f"HTML レポート: {out}")

    return 1 if failures or not invariance_ok else 0


if __name__ == "__main__":
    sys.exit(main())
