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
        self.geometry("320x200")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # --- テーマ ---
        theme_frame = ctk.CTkFrame(self)
        theme_frame.grid(row=0, column=0, padx=16, pady=(16, 4), sticky="ew")
        theme_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(theme_frame, text="テーマ:").grid(
            row=0, column=0, padx=(8, 4), pady=8, sticky="w"
        )
        self._theme_var = ctk.StringVar(
            value=self._settings.get("theme", "system")
        )
        self._theme_menu = ctk.CTkOptionMenu(
            theme_frame, values=["system", "light", "dark"],
            variable=self._theme_var, width=100,
        )
        self._theme_menu.grid(row=0, column=1, padx=(4, 8), pady=8, sticky="w")

        # --- 言語 ---
        lang_frame = ctk.CTkFrame(self)
        lang_frame.grid(row=1, column=0, padx=16, pady=4, sticky="ew")
        lang_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(lang_frame, text="言語 / Language:").grid(
            row=0, column=0, padx=(8, 4), pady=8, sticky="w"
        )
        self._lang_var = ctk.StringVar(
            value=self._settings.get("language", "日本語")
        )
        self._lang_menu = ctk.CTkOptionMenu(
            lang_frame, values=["日本語", "English"],
            variable=self._lang_var, width=100,
        )
        self._lang_menu.grid(row=0, column=1, padx=(4, 8), pady=8, sticky="w")

        # --- ボタン ---
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=2, column=0, padx=16, pady=(8, 16), sticky="se")
        btn_frame.grid_columnconfigure((0, 1), weight=0)

        ctk.CTkButton(btn_frame, text="キャンセル", command=self.destroy).grid(
            row=0, column=0, padx=(0, 4),
        )
        ctk.CTkButton(btn_frame, text="保存", command=self._on_save).grid(
            row=0, column=1, padx=(4, 0),
        )

    def _on_save(self) -> None:
        """設定を保存して閉じる"""
        theme = self._theme_var.get()
        self._settings.set("theme", theme)
        self._settings.set("language", self._lang_var.get())

        if self._on_theme_changed is not None:
            self._on_theme_changed(theme)

        self.destroy()
