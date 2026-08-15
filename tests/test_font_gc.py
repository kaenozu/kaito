"""
tests/test_font_gc.py
一時 CTkFont の GC フォールバック回帰テスト

ttk スタイルに一時 CTkFont を渡すと、参照切れオブジェクトの GC で名前付き
フォントが Tk から失われ、Tk デフォルト（日本語 Windows では MS PGothic
14pt など）へフォールバックする問題があった（fix 2132c9f）。

本テストは実 Tk ルートを立てて以下を固定する:
- CTk ウィジェットは渡された CTkFont を参照保持するため、GC 後もフォントが
  Segoe UI に解決されること（監査: 2026-08）
- ttk.Treeview はフォント指定タプル（正数 = ピクセル）を使うため、GC と
  無関係に Segoe UI 12px へ解決されること
"""

import gc
import weakref
from tkinter import ttk

import customtkinter as ctk
import pytest
import tkinter as tk

from kaito.gui import theme


@pytest.fixture(scope="module")
def root():
    """実 Tk ルート（利用できない環境ではスキップ）

    モジュールスコープで1個だけ生成する（Windows の tkinter は生成→破棄→
    再生成を繰り返すと間欠的に Tcl 初期化に失敗するため）。
    """
    try:
        r = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - ヘッドレス環境等
        pytest.skip(f"Tk を利用できない環境です: {exc}")
    r.withdraw()
    yield r
    r.destroy()


def _build_ctk_widgets(root):
    """アプリで使用する CTk ウィジェット群を一時 CTkFont 付きで生成する"""
    return [
        ctk.CTkButton(root, text="b", font=theme.font(13, "bold")),
        ctk.CTkLabel(root, text="l", font=theme.font(13)),
        ctk.CTkEntry(root, font=theme.ui_font(12)),
        ctk.CTkOptionMenu(
            root, values=["a"], font=theme.font(13), dropdown_font=theme.font(13)
        ),
        ctk.CTkCheckBox(root, text="c", font=theme.font(13)),
        ctk.CTkTextbox(root, font=theme.ui_font(12)),
        ctk.CTkComboBox(
            root, values=["a"], font=theme.font(13), dropdown_font=theme.font(13)
        ),
        ctk.CTkSegmentedButton(root, values=["a"], font=theme.font(13)),
    ]


def _font_actual(root, widget, option=None):
    """ウィジェットのフォントを Tk に問い合わせて解決する"""
    f = widget.cget(option) if option else widget.cget("font")
    return root.tk.call("font", "actual", str(f))


class TestCtkWidgetsHoldFontReferences:
    """CTk ウィジェットは渡した一時 CTkFont を参照保持し GC 後も解決できる"""

    def test_font_survives_gc(self, root) -> None:
        """font= で渡した一時 CTkFont は GC 後も Segoe UI に解決される"""
        widgets = _build_ctk_widgets(root)
        gc.collect()
        for w in widgets:
            actual = _font_actual(root, w)
            assert "-family" in actual and "Segoe UI" in str(actual), (
                type(w).__name__,
                actual,
            )

    def test_dropdown_font_survives_gc(self, root) -> None:
        """dropdown_font= も同様に GC 後も Segoe UI に解決される"""
        widgets = _build_ctk_widgets(root)
        gc.collect()
        for w in widgets:
            if isinstance(w, (ctk.CTkOptionMenu, ctk.CTkComboBox)):
                actual = _font_actual(root, w, "dropdown_font")
                assert "-family" in actual and "Segoe UI" in str(actual), (
                    type(w).__name__,
                    actual,
                )

    def test_widget_holds_reference_to_passed_font(self, root) -> None:
        """渡した CTkFont と同一オブジェクトをウィジェットが保持する（監査の根拠）"""
        font = theme.font(13)
        ref = weakref.ref(font)
        button = ctk.CTkButton(root, text="b", font=font)
        del font
        gc.collect()
        assert ref() is not None  # ウィジェットが保持しているため GC されない
        assert button.cget("font") is ref()


class TestTreeStyleTuple:
    """ttk.Treeview はフォント指定タプル（正数=px）を使い GC の影響を受けない"""

    def test_tree_style_resolves_after_gc(self, root) -> None:
        """スタイルにタプル指定したフォントが GC 後も Segoe UI 12px に解決される"""
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(
            "Treeview",
            font=(theme.TREE_FONT_FAMILY, theme.TREE_FONT_SIZE),
        )
        ttk.Treeview(root)
        root.update_idletasks()
        gc.collect()
        spec = style.lookup("Treeview", "font")
        actual = root.tk.call("font", "actual", spec)
        assert actual[1] == theme.TREE_FONT_FAMILY
        assert int(actual[3]) == theme.TREE_FONT_SIZE
