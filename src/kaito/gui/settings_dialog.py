"""
src/kaito/gui/settings_dialog.py
設定ダイアログ (CTkToplevel モーダル)
テーマ, 言語などのアプリ設定を変更する
関連: unzip_app.py (親ウィンドウ), settings.py (設定保存)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import customtkinter as ctk

if TYPE_CHECKING:
    from kaito.settings import SettingsManager


class SettingsDialog(ctk.CTkToplevel):
    """アプリ設定を変更するモーダルダイアログ"""

    def __init__(  # pragma: no cover
        self,
        parent: ctk.CTk,
        settings: SettingsManager,
        on_theme_changed: Callable[[str], object] | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._on_theme_changed = on_theme_changed

        self.title("設定")
        self.geometry("400x340")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(
            self,
            text="kaito の設定",
            font=ctk.CTkFont(size=20, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=24, pady=(22, 2), sticky="w")
        ctk.CTkLabel(
            self,
            text="使い方に合わせて外観と圧縮速度を調整できます",
            text_color=("#667085", "#a9b4c2"),
            anchor="w",
        ).grid(row=1, column=0, padx=24, pady=(0, 14), sticky="w")

        # --- テーマ ---
        theme_frame = ctk.CTkFrame(self)
        theme_frame.grid(row=2, column=0, padx=24, pady=4, sticky="ew")
        theme_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(theme_frame, text="テーマ:").grid(
            row=0, column=0, padx=(8, 4), pady=8, sticky="w"
        )
        self._theme_var = ctk.StringVar(value=self._settings.get("theme", "system"))
        self._theme_menu = ctk.CTkOptionMenu(
            theme_frame,
            values=["system", "light", "dark"],
            variable=self._theme_var,
            width=100,
        )
        self._theme_menu.grid(row=0, column=1, padx=(4, 8), pady=8, sticky="w")

        # --- 言語 ---
        lang_frame = ctk.CTkFrame(self)
        lang_frame.grid(row=3, column=0, padx=24, pady=4, sticky="ew")
        lang_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(lang_frame, text="言語 / Language:").grid(
            row=0, column=0, padx=(8, 4), pady=8, sticky="w"
        )
        self._lang_var = ctk.StringVar(value=self._settings.get("language", "日本語"))
        self._lang_menu = ctk.CTkOptionMenu(
            lang_frame,
            values=["日本語", "English"],
            variable=self._lang_var,
            width=100,
        )
        self._lang_menu.grid(row=0, column=1, padx=(4, 8), pady=8, sticky="w")

        # --- 圧縮速度 ---
        compression_frame = ctk.CTkFrame(self)
        compression_frame.grid(row=4, column=0, padx=24, pady=4, sticky="ew")
        compression_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(compression_frame, text="圧縮速度:").grid(
            row=0, column=0, padx=(12, 4), pady=(10, 0), sticky="w"
        )
        self._compression_var = ctk.StringVar(
            value=self._compression_label(self._settings.get("compression_level", 1))
        )
        ctk.CTkOptionMenu(
            compression_frame,
            values=["最速（サイズ大）", "標準", "高圧縮（時間長）"],
            variable=self._compression_var,
            width=170,
        ).grid(row=0, column=1, padx=(4, 12), pady=(10, 0), sticky="e")
        ctk.CTkLabel(
            compression_frame,
            text="最速を選ぶと圧縮処理が軽くなります",
            text_color=("#667085", "#a9b4c2"),
            anchor="w",
        ).grid(row=1, column=0, columnspan=2, padx=12, pady=(2, 10), sticky="w")

        # --- ボタン ---
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=5, column=0, padx=24, pady=(12, 20), sticky="e")
        btn_frame.grid_columnconfigure((0, 1), weight=0)

        ctk.CTkButton(btn_frame, text="キャンセル", command=self.destroy).grid(
            row=0,
            column=0,
            padx=(0, 4),
        )
        ctk.CTkButton(btn_frame, text="保存", command=self._on_save).grid(
            row=0,
            column=1,
            padx=(4, 0),
        )

    def _on_save(self) -> None:
        """設定を保存して閉じる"""
        theme = self._theme_var.get()
        self._settings.set("theme", theme)
        self._settings.set("language", self._lang_var.get())
        self._settings.set("compression_level", self._compression_level())

        if self._on_theme_changed is not None:
            self._on_theme_changed(theme)

        self.destroy()

    def _compression_label(self, level: object) -> str:
        try:
            i = int(str(level))
        except (ValueError, TypeError):
            i = 1
        return {1: "最速（サイズ大）", 6: "標準", 9: "高圧縮（時間長）"}.get(
            i, "最速（サイズ大）"
        )

    def _compression_level(self) -> int:
        return {"最速（サイズ大）": 1, "標準": 6, "高圧縮（時間長）": 9}.get(
            self._compression_var.get(), 1
        )
