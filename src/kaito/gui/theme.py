"""
src/kaito/gui/theme.py
アプリ全体のビジュアルトークン（色・フォント・レイアウト定数）

ライト/ダーク両対応の色は (light, dark) のタプルで定義し、appearance mode に応じて
pick() で選択する。単一色（アクセント等）はそのまま使う。
customtkinter の内蔵カラーテーマ色に頼らず、ここで定義したカードベースの
デザインシステムで統一する。
"""

from typing import Literal

import customtkinter as ctk

# --- アクセントカラー（ライト/ダーク共通） ---
# 白文字とのコントラスト比を WCAG 1.4.11 (3:1) 以上に保てる色を選ぶ
ACCENT = "#3b82f6"
ACCENT_HOVER = "#2f6ee0"
ACCENT_ON = "#ffffff"  # アクセント面の上に載せるテキスト色

# --- サーフェス（背景とカード） ---
# BG: ウィンドウ背景 / SURFACE: カード / SURFACE_2: 内蔵面（入力・セカンダリボタン）
BG = ("#f3f5fa", "#0f1117")
SURFACE = ("#ffffff", "#1b1e27")
SURFACE_2 = ("#eef1f6", "#272c38")
BORDER = ("#e2e6ef", "#2d3341")

# --- テキスト ---
TEXT = ("#16181d", "#e7ecf5")
SUBTEXT = ("#677085", "#9aa4b4")

# アクセントの淡い面（選択・ハイライト背景など）
ACCENT_SOFT = ("#eaf1ff", "#1c2b4a")

# --- ドロップゾーン境界 ---
DROP_BORDER = ("#bcc9e6", "#3b4b6a")
DROP_HIGHLIGHT = ("#3b82f6", "#6fa3ff")

# ステータス文字色（ライト側は白背景で WCAG AA 4.5:1 を満たす色）
TEXT_ERROR = ("#c0392b", "#f1948a")
TEXT_SUCCESS = ("#15803d", "#7ed6a0")
TEXT_WARN = ("#b45309", "#f5c76a")

# --- ttk.Treeview ---
TREE_LIGHT_BG = "#ffffff"
TREE_LIGHT_FG = "#16181d"
TREE_LIGHT_HEADER = "#f4f6fa"
TREE_LIGHT_HEADER_ACTIVE = "#e4e8f0"
TREE_LIGHT_SELECT_BG = "#dce9ff"
TREE_LIGHT_SELECT_FG = "#16181d"
TREE_DARK_BG = "#1b1e27"
TREE_DARK_FG = "#dce4ee"
TREE_DARK_HEADER = "#212530"
TREE_DARK_HEADER_ACTIVE = "#2a303e"
TREE_DARK_SELECT_BG = "#2b4d78"
TREE_DARK_SELECT_FG = "#ffffff"
TREE_ROW_HEIGHT = 34

# --- フォント ---
FONT_FAMILY = "Yu Gothic UI"


def font(size: int = 13, weight: Literal["normal", "bold"] = "normal") -> ctk.CTkFont:
    """アプリ標準フォントを作成する"""
    return ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)


def pick(pair: tuple[str, str], is_dark: bool) -> str:
    """(light, dark) タプルから現在の appearance mode に合う色を返す"""
    return pair[1] if is_dark else pair[0]


def is_dark() -> bool:
    """現在の実際の外観モードがdarkかどうかを返す（systemを解決）"""
    mode = ctk.get_appearance_mode().lower()
    if mode == "system":
        try:
            import darkdetect
            return bool(darkdetect.isDark())
        except ImportError:  # pragma: no cover
            return False
    return mode == "dark"


def primary_button(
    parent: ctk.CTkBaseClass,
    text: str,
    command,
    width: int = 100,
    height: int = 40,
    font_size: int = 13,
    bold: bool = False,
) -> ctk.CTkButton:
    """アクセント塗りのプライマリボタン"""
    return ctk.CTkButton(
        parent, text=text, width=width, height=height,
        fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=ACCENT_ON,
        corner_radius=10, font=font(font_size, "bold" if bold else "normal"),
        command=command,
    )


def secondary_button(
    parent: ctk.CTkBaseClass,
    text: str,
    command,
    is_dark: bool,
    width: int = 100,
    height: int = 40,
    font_size: int = 13,
    border_color: str | None = None,
    text_color: str | None = None,
) -> ctk.CTkButton:
    """枠線付きのセカンダリボタン"""
    return ctk.CTkButton(
        parent, text=text, width=width, height=height,
        fg_color=pick(SURFACE_2, is_dark),
        hover_color=pick(BORDER, is_dark),
        border_width=1, border_color=border_color or pick(BORDER, is_dark),
        text_color=text_color or pick(TEXT, is_dark),
        corner_radius=10, font=font(font_size), command=command,
    )


def card(
    parent: object,
    is_dark: bool,
    corner_radius: int = 16,
) -> ctk.CTkFrame:
    """カード面（境界線付きの白/ダークカード）"""
    return ctk.CTkFrame(
        parent, corner_radius=corner_radius,
        fg_color=pick(SURFACE, is_dark),
        border_width=1, border_color=pick(BORDER, is_dark),
    )


def option_menu(
    parent: object,
    values: list[str],
    variable: ctk.Variable,
    is_dark: bool,
    width: int = 140,
    height: int = 34,
    command=None,
) -> ctk.CTkOptionMenu:
    """デザインシステム準拠のドロップダウンメニュー"""
    return ctk.CTkOptionMenu(
        parent, values=values, variable=variable, width=width, height=height,
        corner_radius=10, fg_color=pick(SURFACE_2, is_dark),
        button_color=pick(SURFACE_2, is_dark),
        button_hover_color=pick(BORDER, is_dark),
        text_color=pick(TEXT, is_dark),
        dropdown_fg_color=pick(SURFACE, is_dark),
        dropdown_hover_color=pick(ACCENT_SOFT, is_dark),
        dropdown_text_color=pick(TEXT, is_dark),
        font=font(13), dropdown_font=font(13), command=command,
    )
