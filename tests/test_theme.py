"""
tests/test_theme.py
テーマのコントラスト検証（ライト/ダーク両モード）

- 本文・補助・ステータステキスト: WCAG AA (4.5:1) 以上
- UI部品（ボタン文字・アイコン）: WCAG 1.4.11 (3:1) 以上
- カラートークンのスナップショット: 色の意図しない変更を検出する
"""

import pytest

from kaito.gui import theme

LIGHT = False
DARK = True

# ---- コントラスト計算 (WCAG 2.x) ----

def _channel(value: int) -> float:
    value /= 255
    if value <= 0.03928:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def _luminance(color: str) -> float:
    h = color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def _contrast(fg: str, bg: str) -> float:
    l1, l2 = _luminance(fg), _luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


class TestTextContrast:
    """本文・補助テキストは WCAG AA (4.5:1) 以上"""

    @pytest.mark.parametrize("is_dark", (LIGHT, DARK), ids=("light", "dark"))
    def test_primary_text(self, is_dark: bool) -> None:
        text = theme.pick(theme.TEXT, is_dark)
        assert _contrast(text, theme.pick(theme.BG, is_dark)) >= 4.5
        assert _contrast(text, theme.pick(theme.SURFACE, is_dark)) >= 4.5

    @pytest.mark.parametrize("is_dark", (LIGHT, DARK), ids=("light", "dark"))
    def test_subtext(self, is_dark: bool) -> None:
        sub = theme.pick(theme.SUBTEXT, is_dark)
        assert _contrast(sub, theme.pick(theme.BG, is_dark)) >= 4.5
        assert _contrast(sub, theme.pick(theme.SURFACE, is_dark)) >= 4.5

    @pytest.mark.parametrize("pair", ("TEXT_ERROR", "TEXT_SUCCESS", "TEXT_WARN"))
    @pytest.mark.parametrize("is_dark", (LIGHT, DARK), ids=("light", "dark"))
    def test_status_colors(self, pair: str, is_dark: bool) -> None:
        color = theme.pick(getattr(theme, pair), is_dark)
        assert _contrast(color, theme.pick(theme.SURFACE, is_dark)) >= 4.5


class TestUiContrast:
    """UI部品（ボタン文字・アイコン）は WCAG 1.4.11 (3:1) 以上"""

    def test_accent_button_label(self) -> None:
        assert _contrast(theme.ACCENT_ON, theme.ACCENT) >= 3.0
        assert _contrast(theme.ACCENT_ON, theme.ACCENT_HOVER) >= 3.0

    @pytest.mark.parametrize("is_dark", (LIGHT, DARK), ids=("light", "dark"))
    def test_accent_icon_on_soft(self, is_dark: bool) -> None:
        assert _contrast(theme.ACCENT, theme.pick(theme.ACCENT_SOFT, is_dark)) >= 3.0


class TestTreeContrast:
    """ファイル一覧（ツリー）のテキストは 4.5:1 以上"""

    @pytest.mark.parametrize("is_dark", (LIGHT, DARK), ids=("light", "dark"))
    def test_tree_rows_and_header(self, is_dark: bool) -> None:
        prefix = "TREE_DARK" if is_dark else "TREE_LIGHT"
        bg = getattr(theme, f"{prefix}_BG")
        fg = getattr(theme, f"{prefix}_FG")
        assert _contrast(fg, bg) >= 4.5
        header = getattr(theme, f"{prefix}_HEADER")
        assert _contrast(fg, header) >= 4.5

    @pytest.mark.parametrize("is_dark", (LIGHT, DARK), ids=("light", "dark"))
    def test_tree_selection(self, is_dark: bool) -> None:
        prefix = "TREE_DARK" if is_dark else "TREE_LIGHT"
        sel_fg = getattr(theme, f"{prefix}_SELECT_FG")
        sel_bg = getattr(theme, f"{prefix}_SELECT_BG")
        assert _contrast(sel_fg, sel_bg) >= 4.5


class TestThemeSnapshot:
    """カラートークンのスナップショット（意図しない色変更を検出する）"""

    SNAPSHOT = {
        # アクセント
        "ACCENT": "#3b82f6",
        "ACCENT_HOVER": "#2f6ee0",
        "ACCENT_ON": "#ffffff",
        # サーフェス
        "BG": ("#f3f5fa", "#0f1117"),
        "SURFACE": ("#ffffff", "#1b1e27"),
        "SURFACE_2": ("#eef1f6", "#272c38"),
        "BORDER": ("#e2e6ef", "#2d3341"),
        # テキスト
        "TEXT": ("#16181d", "#e7ecf5"),
        "SUBTEXT": ("#677085", "#9aa4b4"),
        "ACCENT_SOFT": ("#eaf1ff", "#1c2b4a"),
        # ドロップゾーン
        "DROP_BORDER": ("#bcc9e6", "#3b4b6a"),
        "DROP_HIGHLIGHT": ("#3b82f6", "#6fa3ff"),
        # ステータス
        "TEXT_ERROR": ("#c0392b", "#f1948a"),
        "TEXT_SUCCESS": ("#15803d", "#7ed6a0"),
        "TEXT_WARN": ("#b45309", "#f5c76a"),
        # ツリー
        "TREE_LIGHT_BG": "#ffffff",
        "TREE_LIGHT_FG": "#16181d",
        "TREE_LIGHT_HEADER": "#f4f6fa",
        "TREE_LIGHT_HEADER_ACTIVE": "#e4e8f0",
        "TREE_LIGHT_SELECT_BG": "#dce9ff",
        "TREE_LIGHT_SELECT_FG": "#16181d",
        "TREE_DARK_BG": "#1b1e27",
        "TREE_DARK_FG": "#dce4ee",
        "TREE_DARK_HEADER": "#212530",
        "TREE_DARK_HEADER_ACTIVE": "#2a303e",
        "TREE_DARK_SELECT_BG": "#2b4d78",
        "TREE_DARK_SELECT_FG": "#ffffff",
    }

    def test_snapshot_matches(self) -> None:
        """トークンの値が承認済みスナップショットと一致する"""
        for name, expected in self.SNAPSHOT.items():
            actual = getattr(theme, name)
            assert actual == expected, (
                f"{name} が変更されました: {actual!r} != {expected!r}。"
                "意図的な変更なら test_theme.py の SNAPSHOT も更新してください。"
            )

    def test_snapshot_covers_all_color_tokens(self) -> None:
        """theme.py の全色トークンがスナップショットに漏れなく含まれる"""
        color_tokens: set[str] = set()
        for name in dir(theme):
            if name.startswith("_"):
                continue
            value = getattr(theme, name)
            if isinstance(value, str) and value.startswith("#"):
                color_tokens.add(name)
            elif (
                isinstance(value, tuple) and len(value) == 2
                and all(isinstance(c, str) and c.startswith("#") for c in value)
            ):
                color_tokens.add(name)
        assert color_tokens == set(self.SNAPSHOT)
