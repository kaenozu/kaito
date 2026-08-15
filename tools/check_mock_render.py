"""
tools/check_mock_render.py
モックの CSS 変数（theme.py トークンの写し）が実アプリの画面描画と一致するかを
スクリーンショット解析で検証する（tools/font_audit.py の実インク計測と同じ手法）。

- theme.py のトークンで実際の Tk ウィジェット（CTkFrame スウォッチ / プライマリボタン /
  ttk.Treeview）をライト/ダーク両モードで描画し、ImageGrab でキャプチャして
  各領域の画素を実測する
- 実測値と theme.py トークン・モックの CSS 変数（preview/index.html）を突合する
- キャプチャ不可環境（ヘッドレス・他ウィンドウに隠れる等）では実描画列が N/A に
  自動降格し、exit code はモック↔theme.py の突合結果（ファイル解析のみで決定的）に基づく

文字色（TEXT / TREE fg / 選択行文字色）はアンチエイリアスにより画素実測に不向きなため、
塗り面・背景・ボーダー系トークンを対象とする。

使い方:
    uv run python tools/check_mock_render.py             # 標準出力 + preview/check-mock-render.html
    uv run python tools/check_mock_render.py --no-html   # 標準出力のみ
    uv run python tools/check_mock_render.py --skip-capture  # 実描画の計測をスキップ
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from tkinter import ttk
from typing import Any

import customtkinter as ctk
from PIL import Image, ImageGrab

from kaito.gui import theme

import check_mock_theme  # tools/ 内の検査モジュール（CSS 変数パースを再利用）

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
TOLERANCE = 3  # RGB 各チャンネルの許容差


def _expected_hex(spec: str | tuple[str, str], is_dark: bool) -> str:
    """トークン指定 → モード別の期待色 (theme.py から取得)"""
    if isinstance(spec, tuple):
        return getattr(theme, spec[1] if is_dark else spec[0])
    val = getattr(theme, spec)
    if isinstance(val, tuple):
        return val[1] if is_dark else val[0]
    return val


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)


def _close(px: tuple[int, ...], hex_color: str, tol: int = TOLERANCE) -> bool:
    return all(abs(a - b) <= tol for a, b in zip(px, _rgb(hex_color)))


def _apply_tree_style(style: ttk.Style, is_dark: bool) -> None:
    """unzip_app._apply_tree_style と同一構成でツリースタイルを適用する"""
    if is_dark:
        bg, fg, heading_bg = (
            theme.TREE_DARK_BG,
            theme.TREE_DARK_FG,
            theme.TREE_DARK_HEADER,
        )
        selected_bg, selected_fg = theme.TREE_DARK_SELECT_BG, theme.TREE_DARK_SELECT_FG
        heading_active = theme.TREE_DARK_HEADER_ACTIVE
    else:
        bg, fg, heading_bg = (
            theme.TREE_LIGHT_BG,
            theme.TREE_LIGHT_FG,
            theme.TREE_LIGHT_HEADER,
        )
        selected_bg, selected_fg = (
            theme.TREE_LIGHT_SELECT_BG,
            theme.TREE_LIGHT_SELECT_FG,
        )
        heading_active = theme.TREE_LIGHT_HEADER_ACTIVE
    style.theme_use("clam")
    style.configure(
        "Treeview",
        background=bg,
        foreground=fg,
        fieldbackground=bg,
        borderwidth=0,
        rowheight=theme.TREE_ROW_HEIGHT,
        font=(theme.TREE_FONT_FAMILY, theme.TREE_FONT_SIZE),
    )
    style.configure(
        "Treeview.Heading",
        background=heading_bg,
        foreground=fg,
        relief="flat",
        font=(theme.TREE_FONT_FAMILY, theme.TREE_FONT_SIZE, "bold"),
    )
    style.map(
        "Treeview",
        background=[("selected", selected_bg)],
        foreground=[("selected", selected_fg)],
    )
    style.map("Treeview.Heading", background=[("active", heading_active)])


def _capture(root: ctk.CTk) -> tuple[Image.Image, int, int] | None:
    """ウィンドウ全体をキャプチャ。単色（隠蔽等）なら None"""
    root.update()
    time.sleep(0.4)
    root.update()
    ox, oy = root.winfo_rootx(), root.winfo_rooty()
    w, h = root.winfo_width(), root.winfo_height()
    try:
        img = ImageGrab.grab(bbox=(ox, oy, ox + w, oy + h)).convert("RGB")
    except Exception as exc:  # pragma: no cover - ヘッドレス/権限なし等
        print(f"  (実描画の計測をスキップ: {exc})")
        return None
    lo, hi = img.convert(
        "L"
    ).getextrema()  # 単色/真っ黒 = 他ウィンドウに隠れている可能性
    if not isinstance(lo, (int, float)) or not isinstance(
        hi, (int, float)
    ):  # pragma: no cover
        print("  (実描画の計測をスキップ: キャプチャ形式が想定外です)")
        return None
    if hi - lo < 12:  # pragma: no cover - キャプチャ不可環境
        print("  (実描画の計測をスキップ: キャプチャが単色で内容を検出できません)")
        return None
    return img, ox, oy


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-html", action="store_true", help="HTML レポートを生成しない"
    )
    parser.add_argument(
        "--skip-capture", action="store_true", help="実描画の計測をスキップ"
    )
    args = parser.parse_args()

    html = INDEX.read_text(encoding="utf-8")
    blocks = check_mock_theme._css_blocks(html)

    root = ctk.CTk()
    root.geometry("840x700")
    root.attributes("-topmost", True)
    root.configure(fg_color=theme.BG[0])

    ctk.CTkLabel(
        root,
        text="check_mock_render — theme.py token swatches",
        font=theme.font(14, "bold"),
    ).pack(padx=10, pady=(10, 2))
    container = ctk.CTkFrame(root, corner_radius=0, fg_color="transparent")
    container.pack(fill="both", expand=True, padx=10, pady=4)

    # --- スウォッチ定義: (表示名, CSS 変数, トークン指定) ---
    swatch_specs: list[tuple[str, str, str | tuple[str, str]]] = [
        ("ACCENT", "--accent", "ACCENT"),
        ("ACCENT_HOVER", "--accent-hover", "ACCENT_HOVER"),
        ("BG", "--bg", "BG"),
        ("SURFACE", "--panel", "SURFACE"),
        ("SURFACE_2", "--panel-2", "SURFACE_2"),
        ("BORDER", "--border", "BORDER"),
        ("TEXT", "--text", "TEXT"),
        ("SUBTEXT", "--muted", "SUBTEXT"),
        ("ACCENT_SOFT", "--accent-soft", "ACCENT_SOFT"),
        ("DROP_BORDER", "--drop-border", "DROP_BORDER"),
        ("DROP_HIGHLIGHT", "--drop-hl", "DROP_HIGHLIGHT"),
    ]
    swatches: list[ctk.CTkFrame] = []
    for i in range(0, len(swatch_specs), 4):
        row_frame = ctk.CTkFrame(container, fg_color="transparent")
        row_frame.pack(fill="x", pady=3)
        for label, _var, spec in swatch_specs[i : i + 4]:
            sw = ctk.CTkFrame(
                row_frame,
                height=40,
                fg_color=_expected_hex(spec, False),
                corner_radius=6,
            )
            sw.pack(side="left", fill="both", expand=True, padx=4)
            swatches.append(sw)

    # --- 実ウィジェット ---
    btn = theme.primary_button(
        container, text="抽出", command=lambda: None, width=120, height=40
    )
    btn.pack(pady=(8, 2))

    style = ttk.Style(container)
    tree = ttk.Treeview(
        container, columns=("name", "size", "pad"), show="headings", height=3
    )
    tree.heading("name", text="名前")
    tree.heading("size", text="サイズ")
    tree.heading("pad", text="")
    tree.column("name", width=200, anchor="w")
    tree.column("size", width=90, anchor="e")
    tree.column("pad", width=100, anchor="w")
    tree.insert("", "end", iid="r0", values=("sample.txt", "1 KB", ""))
    tree.selection_set("r0")
    tree.pack(fill="x", pady=(6, 4))

    # --- 領域定義（サンプリング位置は各パスで winfo から計算） ---
    regions: list[dict[str, Any]] = [
        {
            "label": "swatch ACCENT",
            "var": "--accent",
            "spec": "ACCENT",
            "kind": "center",
            "w": swatches[0],
        },
        {
            "label": "swatch ACCENT_HOVER",
            "var": "--accent-hover",
            "spec": "ACCENT_HOVER",
            "kind": "center",
            "w": swatches[1],
        },
        {
            "label": "swatch BG",
            "var": "--bg",
            "spec": "BG",
            "kind": "center",
            "w": swatches[2],
        },
        {
            "label": "swatch SURFACE",
            "var": "--panel",
            "spec": "SURFACE",
            "kind": "center",
            "w": swatches[3],
        },
        {
            "label": "swatch SURFACE_2",
            "var": "--panel-2",
            "spec": "SURFACE_2",
            "kind": "center",
            "w": swatches[4],
        },
        {
            "label": "swatch BORDER",
            "var": "--border",
            "spec": "BORDER",
            "kind": "center",
            "w": swatches[5],
        },
        {
            "label": "swatch TEXT",
            "var": "--text",
            "spec": "TEXT",
            "kind": "center",
            "w": swatches[6],
        },
        {
            "label": "swatch SUBTEXT",
            "var": "--muted",
            "spec": "SUBTEXT",
            "kind": "center",
            "w": swatches[7],
        },
        {
            "label": "swatch ACCENT_SOFT",
            "var": "--accent-soft",
            "spec": "ACCENT_SOFT",
            "kind": "center",
            "w": swatches[8],
        },
        {
            "label": "swatch DROP_BORDER",
            "var": "--drop-border",
            "spec": "DROP_BORDER",
            "kind": "center",
            "w": swatches[9],
        },
        {
            "label": "swatch DROP_HIGHLIGHT",
            "var": "--drop-hl",
            "spec": "DROP_HIGHLIGHT",
            "kind": "center",
            "w": swatches[10],
        },
        {
            "label": "primary_button (抽出)",
            "var": "--accent",
            "spec": "ACCENT",
            "kind": "button_left",
            "w": btn,
        },
        {
            "label": "tree header (pad列)",
            "var": "--tree-head-bg",
            "spec": ("TREE_LIGHT_HEADER", "TREE_DARK_HEADER"),
            "kind": "tree_header",
        },
        {
            "label": "tree selected row",
            "var": "--tree-sel-bg",
            "spec": ("TREE_LIGHT_SELECT_BG", "TREE_DARK_SELECT_BG"),
            "kind": "tree_sel",
        },
        {
            "label": "tree bg (空行)",
            "var": "--panel",
            "spec": ("TREE_LIGHT_BG", "TREE_DARK_BG"),
            "kind": "tree_bg",
        },
    ]

    # --- モード別パス ---
    captured: dict[str, dict[str, tuple[int, ...] | None]] = {}  # label -> {mode: rgb}
    try:
        for is_dark in (False, True):
            mode = "dark" if is_dark else "light"
            ctk.set_appearance_mode(mode)
            root.configure(fg_color=_expected_hex("BG", is_dark))
            for sw, (_label, _var, spec) in zip(swatches, swatch_specs):
                sw.configure(fg_color=_expected_hex(spec, is_dark))
            _apply_tree_style(style, is_dark)

            if args.skip_capture:
                break
            shot = _capture(root)
            if shot is None:
                break
            img, ox, oy = shot

            row_bbox = tree.bbox("r0")  # 選択行の全体矩形（tree 座標）
            pad_bbox = tree.bbox("r0", "pad")  # pad 列セル（tree 座標）
            if row_bbox is None or pad_bbox is None:  # pragma: no cover
                raise RuntimeError("tree bbox が取得できません")
            rx, ry, rw, rh = (int(v) for v in row_bbox)
            pad_x0, _py, pad_w, _ph = (int(v) for v in pad_bbox)
            tx, ty = tree.winfo_rootx() - ox, tree.winfo_rooty() - oy
            th = tree.winfo_height()
            pad_x = tx + pad_x0 + pad_w // 2

            def point(r: dict[str, Any]) -> tuple[int, int]:
                kind = str(r["kind"])
                if kind == "center" or kind == "button_left":
                    w = r["w"]
                    assert isinstance(w, (ctk.CTkFrame, ctk.CTkButton))
                    if kind == "center":
                        return (
                            w.winfo_rootx() - ox + w.winfo_width() // 2,
                            w.winfo_rooty() - oy + w.winfo_height() // 2,
                        )
                    return (
                        w.winfo_rootx() - ox + 10,
                        w.winfo_rooty() - oy + w.winfo_height() // 2,
                    )
                if kind == "tree_header":
                    return (pad_x, ty + 14)
                if kind == "tree_sel":
                    return (tx + rx + rw - 6, ty + ry + rh // 2)
                if kind == "tree_bg":
                    return (pad_x, ty + th - 6)
                raise AssertionError(kind)

            for r in regions:
                x, y = point(r)
                px = img.getpixel((x, y))
                if isinstance(
                    px, tuple
                ):  # RGB のため常にタプル（int はグレースケールのみ）
                    captured.setdefault(str(r["label"]), {})[mode] = px

    finally:
        root.destroy()

    # --- 突合・出力 ---
    failures: list[str] = []
    print(
        "モック CSS 変数 / theme.py トークン / 実アプリ描画の突合（実描画はスクリーンショット解析）:"
    )
    print(
        f"  {'領域':<26}{'変数':<18}{'モード':<7}{'theme.py':<9}{'モックCSS':<9}{'実描画':<9} 判定"
    )
    for r in regions:
        for is_dark in (False, True):
            mode = "dark" if is_dark else "light"
            expected = _expected_hex(r["spec"], is_dark)
            css = check_mock_theme._var_value(
                blocks["dark" if is_dark else "light"], r["var"]
            )
            if css is None:
                css = check_mock_theme._var_value(
                    blocks["light"], r["var"]
                )  # 単一色は :root を継承
            real = captured.get(r["label"], {}).get(mode)
            css_ok = css is not None and css.lower() == expected.lower()
            real_disp = real if real is not None else "N/A"
            if real is not None and _close(real, expected):
                status = "OK"
            elif real is None:
                status = "N/A"
            else:
                status = "NG"
                failures.append(
                    f"  {r['label']} ({mode}): theme.py={expected} モックCSS={css or '継承'} "
                    f"実描画=#{real[0]:02x}{real[1]:02x}{real[2]:02x}"
                )
            if not css_ok:
                status = "NG"
                failures.append(
                    f"  {r['label']}: モックCSS {r['var']}={css or '未定義'} が theme.py の {expected} と不一致"
                )
            if css is None:
                css_disp = "未定義"
            elif css.lower() == expected.lower():
                css_disp = css
            else:
                css_disp = css + "!"
            print(
                f"  {r['label']:<26}{r['var']:<18}{mode:<7}{expected:<9}{css_disp:<9}{real_disp!s:<9} {status}"
            )

    if not args.skip_capture and "N/A" in "".join(
        str(captured.get(r["label"], {}).get(m))
        for r in regions
        for m in ("light", "dark")
    ):
        print(
            "\n(注) 実描画の計測が N/A の環境です。exit code はモック↔theme.py の突合結果に基づきます。"
        )

    if failures:
        print("\nNG:")
        for f in failures:
            print(f)
        return 1

    print("\nOK: 全トークンがモックの CSS 変数・実アプリの描画と一致")
    if not args.no_html:
        out = ROOT / "preview" / "check-mock-render.html"
        rows = "".join(
            f"<tr><td>{r['label']}</td><td><code>{r['var']}</code></td>"
            + "".join(
                _html_cell(r, mode, blocks, captured) for mode in ("light", "dark")
            )
            + "</tr>"
            for r in regions
        )
        out.write_text(
            "<!DOCTYPE html><html lang='ja'><head><meta charset='utf-8'><title>check-mock-render</title>"
            "<style>body{font-family:Segoe UI,system-ui,sans-serif;background:#f3f5fa;padding:20px}"
            "table{border-collapse:collapse;width:100%;background:#fff}th,td{border:1px solid #e2e6ef;"
            "padding:6px 10px;text-align:left;font-size:12.5px}code{background:#eef1f6;border-radius:4px;"
            "padding:1px 5px}</style></head><body><h2>check_mock_render — トークン × 実描画の突合</h2>"
            f"<table><tr><th>領域</th><th>変数</th><th>モード</th><th>theme.py</th><th>モックCSS</th><th>実描画</th></tr>{rows}</table></body></html>",
            encoding="utf-8",
        )
        print(f"HTML レポート: {out.relative_to(ROOT)}")
    return 0


def _html_cell(r: dict, mode: str, blocks: dict[str, str], captured: dict) -> str:
    """HTML テーブル用の 1 セル（モード別の期待値・モックCSS・実描画）を組み立てる"""
    expected = _expected_hex(r["spec"], mode == "dark")
    css = check_mock_theme._var_value(blocks[mode], r["var"])
    if css is None:
        css = check_mock_theme._var_value(blocks["light"], r["var"])
    real = captured.get(r["label"], {}).get(mode)
    real_disp = "N/A" if real is None else f"#{real[0]:02x}{real[1]:02x}{real[2]:02x}"
    css_disp = css if css is not None else "(未定義)"
    return (
        f"<td>{mode}</td><td><code>{expected}</code></td>"
        f"<td><code>{css_disp}</code></td><td><code>{real_disp}</code></td>"
    )


if __name__ == "__main__":
    raise SystemExit(main())
