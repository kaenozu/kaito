"""
src/kaito/gui/settings_dialog.py
設定ダイアログ (CTkToplevel モーダル)
テーマ, 言語などのアプリ設定を変更する
関連: unzip_app.py (親ウィンドウ), settings.py (設定保存), i18n.py (表示言語)
"""

from __future__ import annotations

from collections.abc import Callable
from tkinter import filedialog
from typing import TYPE_CHECKING

import customtkinter as ctk

from kaito.gui import theme
from kaito.i18n import tr

if TYPE_CHECKING:
    from kaito.settings import SettingsManager

# 言語の表示名（各言語の自称で表示するため翻訳しない）
_LANG_LABELS: dict[str, str] = {"ja": "日本語", "en": "English"}


class SettingsDialog(ctk.CTkToplevel):
    """アプリ設定を変更するモーダルダイアログ"""

    def __init__(  # pragma: no cover
        self,
        parent: ctk.CTk,
        settings: SettingsManager,
        on_theme_changed: Callable[[str], object] | None = None,
        on_language_changed: Callable[[str], object] | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._on_theme_changed = on_theme_changed
        self._on_language_changed = on_language_changed

        self.title(tr("settings.title"))
        self.geometry("440x560")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(6, weight=1)

        ctk.CTkLabel(
            self,
            text=tr("settings.heading"),
            font=theme.font(20, "bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=24, pady=(22, 2), sticky="w")
        ctk.CTkLabel(
            self,
            text=tr("settings.subtitle"),
            text_color=theme.SUBTEXT,
            anchor="w",
        ).grid(row=1, column=0, padx=24, pady=(0, 14), sticky="w")

        # --- テーマ ---
        theme_frame = ctk.CTkFrame(self, corner_radius=12)
        theme_frame.grid(row=2, column=0, padx=24, pady=4, sticky="ew")
        theme_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(theme_frame, text=tr("settings.theme"), font=theme.font(13)).grid(
            row=0, column=0, padx=(14, 4), pady=10, sticky="w"
        )
        self._theme_var = ctk.StringVar(value=self._settings.get("theme", "system"))
        self._theme_menu = ctk.CTkOptionMenu(
            theme_frame,
            values=["system", "light", "dark"],
            variable=self._theme_var,
            width=110,
            corner_radius=8,
        )
        self._theme_menu.grid(row=0, column=1, padx=(4, 14), pady=10, sticky="w")

        # --- 言語 ---
        lang_frame = ctk.CTkFrame(self, corner_radius=12)
        lang_frame.grid(row=3, column=0, padx=24, pady=4, sticky="ew")
        lang_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            lang_frame, text=tr("settings.language"), font=theme.font(13)
        ).grid(row=0, column=0, padx=(14, 4), pady=10, sticky="w")
        self._lang_var = ctk.StringVar(
            value=self._lang_label(self._settings.get("language", "ja"))
        )
        self._lang_menu = ctk.CTkOptionMenu(
            lang_frame,
            values=list(_LANG_LABELS.values()),
            variable=self._lang_var,
            width=110,
            corner_radius=8,
        )
        self._lang_menu.grid(row=0, column=1, padx=(4, 14), pady=10, sticky="w")

        # --- 展開先 ---
        dest_frame = ctk.CTkFrame(self, corner_radius=12)
        dest_frame.grid(row=4, column=0, padx=24, pady=4, sticky="ew")
        dest_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            dest_frame, text=tr("settings.dest_mode"), font=theme.font(13)
        ).grid(row=0, column=0, padx=(14, 4), pady=10, sticky="w")
        self._dest_mode_var = ctk.StringVar(
            value=self._dest_mode_label(self._settings.get("dest_mode", "archive"))
        )
        ctk.CTkOptionMenu(
            dest_frame,
            values=[self._dest_mode_label(m) for m in ("archive", "last", "fixed")],
            variable=self._dest_mode_var,
            width=190,
            corner_radius=8,
        ).grid(row=0, column=1, padx=(4, 14), pady=10, sticky="w")
        # 固定フォルダーの指定（"固定フォルダー"モードで使用）
        self._fixed_dest_var = ctk.StringVar(
            value=str(self._settings.get("fixed_dest", ""))
        )
        ctk.CTkLabel(
            dest_frame, text=tr("settings.fixed_dest"), font=theme.font(13)
        ).grid(row=1, column=0, padx=(14, 4), pady=4, sticky="w")
        ctk.CTkEntry(
            dest_frame,
            textvariable=self._fixed_dest_var,
            state="readonly",
        ).grid(row=1, column=1, padx=(4, 4), pady=4, sticky="ew")
        ctk.CTkButton(
            dest_frame,
            text=tr("settings.pick"),
            width=72,
            fg_color="transparent",
            border_width=1,
            border_color="gray65",
            corner_radius=8,
            font=theme.font(12),
            command=self._on_pick_fixed_dest,
        ).grid(row=1, column=2, padx=(0, 14), pady=4)
        ctk.CTkLabel(
            dest_frame,
            text=tr("settings.dest_hint"),
            text_color=theme.SUBTEXT,
            anchor="w",
        ).grid(row=2, column=0, columnspan=3, padx=14, pady=(2, 10), sticky="w")

        # --- 圧縮速度 ---
        compression_frame = ctk.CTkFrame(self, corner_radius=12)
        compression_frame.grid(row=5, column=0, padx=24, pady=4, sticky="ew")
        compression_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            compression_frame, text=tr("settings.compression"), font=theme.font(13)
        ).grid(row=0, column=0, padx=(14, 4), pady=(10, 0), sticky="w")
        self._compression_var = ctk.StringVar(
            value=self._compression_label(self._settings.get("compression_level", 1))
        )
        ctk.CTkOptionMenu(
            compression_frame,
            values=[self._compression_label(level) for level in (1, 6, 9)],
            variable=self._compression_var,
            width=180,
            corner_radius=8,
        ).grid(row=0, column=1, padx=(4, 14), pady=(10, 0), sticky="e")
        ctk.CTkLabel(
            compression_frame,
            text=tr("settings.compression_hint"),
            text_color=theme.SUBTEXT,
            anchor="w",
        ).grid(row=1, column=0, columnspan=2, padx=14, pady=(2, 10), sticky="w")

        # --- プレビュー上限 ---
        preview_frame = ctk.CTkFrame(self, corner_radius=12)
        preview_frame.grid(row=6, column=0, padx=24, pady=4, sticky="ew")
        preview_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            preview_frame,
            text=tr("settings.preview"),
            font=theme.font(13),
        ).grid(row=0, column=0, columnspan=2, padx=14, pady=(8, 2), sticky="w")
        ctk.CTkLabel(
            preview_frame,
            text=tr("settings.preview_max_size"),
            font=theme.font(12),
        ).grid(row=1, column=0, padx=(14, 4), pady=4, sticky="w")
        self._preview_size_var = ctk.StringVar(value=self._preview_size_mb())
        ctk.CTkEntry(
            preview_frame, textvariable=self._preview_size_var, width=120
        ).grid(row=1, column=1, padx=(4, 14), pady=4, sticky="e")
        ctk.CTkLabel(
            preview_frame,
            text=tr("settings.preview_max_pixels"),
            font=theme.font(12),
        ).grid(row=2, column=0, padx=(14, 4), pady=(0, 10), sticky="w")
        self._preview_pixels_var = ctk.StringVar(value=self._preview_pixels_man())
        ctk.CTkEntry(
            preview_frame, textvariable=self._preview_pixels_var, width=120
        ).grid(row=2, column=1, padx=(4, 14), pady=(0, 10), sticky="e")

        # --- ボタン ---
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=7, column=0, padx=24, pady=(12, 20), sticky="e")
        btn_frame.grid_columnconfigure((0, 1), weight=0)

        ctk.CTkButton(
            btn_frame,
            text=tr("app.cancel"),
            width=90,
            fg_color="transparent",
            border_width=1,
            border_color="gray65",
            corner_radius=8,
            font=theme.font(13),
            command=self.destroy,
        ).grid(row=0, column=0, padx=(0, 6), pady=4)
        ctk.CTkButton(
            btn_frame,
            text=tr("settings.save"),
            width=90,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            text_color=theme.ACCENT_ON,
            corner_radius=8,
            font=theme.font(13, "bold"),
            command=self._on_save,
        ).grid(row=0, column=1, padx=(6, 0), pady=4)

    def _on_save(self) -> None:
        """設定を保存して閉じる"""
        theme_mode = self._theme_var.get()
        lang_code = self._lang_code(self._lang_var.get())
        self._settings.set_many(
            {
                "theme": theme_mode,
                "language": lang_code,
                "dest_mode": self._dest_mode_value(),
                "fixed_dest": self._fixed_dest_var.get(),
                "compression_level": self._compression_level(),
                "preview_max_size": self._preview_size_bytes(),
                "preview_max_image_pixels": self._preview_pixels(),
            }
        )

        if self._on_theme_changed is not None:
            self._on_theme_changed(theme_mode)
        if self._on_language_changed is not None:
            self._on_language_changed(lang_code)

        self.destroy()

    def _on_pick_fixed_dest(self) -> None:
        """固定展開先フォルダを選択する"""
        path = filedialog.askdirectory(title=tr("dialog.choose_fixed_dest"))
        if path:
            self._fixed_dest_var.set(path)

    def _lang_label(self, code: object) -> str:
        """言語コード → 表示名（未知のコードは日本語表示）"""
        return _LANG_LABELS.get(str(code), "日本語")

    def _lang_code(self, label: str) -> str:
        """表示名 → 言語コード（未知の表示名は ja）"""
        for code, display in _LANG_LABELS.items():
            if display == label:
                return code
        return "ja"

    def _dest_mode_label(self, mode: object) -> str:
        return {
            "archive": tr("dest.archive"),
            "last": tr("dest.last"),
            "fixed": tr("dest.fixed"),
        }.get(str(mode), tr("dest.archive"))

    def _dest_mode_value(self) -> str:
        for code in ("archive", "last", "fixed"):
            if self._dest_mode_label(code) == self._dest_mode_var.get():
                return code
        return "archive"

    def _compression_label(self, level: object) -> str:
        text = str(level)
        if text.isdigit():
            return {1: tr("comp.fast"), 6: tr("comp.normal"), 9: tr("comp.max")}.get(
                int(text), tr("comp.fast")
            )
        return tr("comp.fast")

    def _compression_level(self) -> int:
        for level, label in {
            1: tr("comp.fast"),
            6: tr("comp.normal"),
            9: tr("comp.max"),
        }.items():
            if label == self._compression_var.get():
                return level
        return 1

    def _preview_size_mb(self) -> str:
        value = self._settings.get("preview_max_size")
        try:
            return str(max(1, int(value) // (1024 * 1024)))
        except (TypeError, ValueError):
            return "10"

    def _preview_pixels_man(self) -> str:
        value = self._settings.get("preview_max_image_pixels")
        try:
            return str(max(1, int(value) // 10_000))
        except (TypeError, ValueError):
            return "1200"

    def _preview_size_bytes(self) -> int:
        try:
            return max(1, int(float(self._preview_size_var.get()) * 1024 * 1024))
        except (ValueError, TypeError):
            return int(self._settings.get("preview_max_size"))

    def _preview_pixels(self) -> int:
        try:
            return max(1, int(float(self._preview_pixels_var.get()) * 10_000))
        except (ValueError, TypeError):
            return int(self._settings.get("preview_max_image_pixels"))
