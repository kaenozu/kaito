"""
src/kaito/gui/unzip_app.py
CustomTkinterを使用したZIP/RAR/7z解凍・圧縮GUIアプリ
ドラッグ&ドロップ対応 (tkinterdnd2)
関連: archive/service.py, settings.py, settings_dialog.py
"""

import io
import locale
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from threading import Event, Thread
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from PIL import Image

import customtkinter as ctk
from tkinterdnd2 import TkinterDnD

from kaito.archive.service import ArchiveService
from kaito.domain.errors import (
    ArchiveError,
    ArchiveBombError,
    CancelledError,
    ExternalToolNotFoundError,
    InvalidPasswordError,
    PasswordRequiredError,
    UnsafeArchiveError,
)
from kaito.domain.models import (
    ArchiveEntry,
    CompressionOptions,
    ExtractionOptions,
    SafetyLimits,
)
from kaito.settings import SettingsManager
from kaito.version import __version__
from kaito.gui.settings_dialog import SettingsDialog

_DROP_BORDER_COLOR = "#3a7ebf"
_DROP_HIGHLIGHT_COLOR = "#1a6ebf"

_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".py",
    ".js",
    ".ts",
    ".html",
    ".css",
    ".json",
    ".xml",
    ".yml",
    ".yaml",
    ".ini",
    ".cfg",
    ".log",
    ".csv",
    ".toml",
}
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".ico"}
_MAX_PREVIEW_CHARS = 2000
_MAX_PREVIEW_FILE_SIZE = 10 * 1024 * 1024  # 10MB


class UnzipApp(ctk.CTk, TkinterDnD.DnDWrapper):
    """アーカイブGUIメインウィンドウ"""

    def __init__(
        self, cli_path: Optional[Path] = None, cli_compress_path: Optional[Path] = None
    ) -> None:
        super().__init__()

        self.TkdndVersion = TkinterDnD._require(self)

        self.title(f"kaito v{__version__}")
        self.geometry("900x600")
        self.minsize(680, 460)

        # 状態管理
        self._current_archive_path: Optional[Path] = None
        self._archive_queue: list[Path] = []
        self._entries: list[ArchiveEntry] = []
        self._is_encrypted = False
        self._is_busy = False
        self._closing = False
        self._worker_thread: Optional[Thread] = None

        self._temp_dir: Optional[tempfile.TemporaryDirectory] = None
        self._current_image: Optional[ctk.CTkImage] = None
        self._prev_preview_token = 0  # プレビュー選択変更検出
        self._compress_sources: list[Path] = []
        self._compress_no_dialog = False
        self._tree_poll_id: Optional[str] = None
        self._recent_display_to_path: dict[str, str] = {}

        # 設定とサービス層
        self._settings = SettingsManager()
        self._archive_service = ArchiveService(
            safety_limits=SafetyLimits(
                max_entries=int(self._settings.get("safety_max_entries")),
                max_total_size=int(self._settings.get("safety_max_total_size")),
                max_single_file_size=int(
                    self._settings.get("safety_max_file_size")
                ),
                max_compression_ratio=float(
                    self._settings.get("safety_max_compression_ratio")
                ),
                max_path_length=int(
                    self._settings.get("safety_max_path_length")
                ),
            )
        )

        # パスワード管理 (アーカイブ単位、メモリ保持のみ)
        self._passwords: dict[str, str] = {}
        self._failed_passwords: set[str] = set()

        self._build_ui()

        self._apply_tree_style()
        self._start_theme_poll()

        self._open_on_done_var.set(self._settings.get("open_on_done", True))
        self._close_on_done_var.set(self._settings.get("close_on_done", False))

        self._refresh_recent_menu()

        # ドラッグ&ドロップ設定
        self.drop_target_register("*")
        self.dnd_bind("<<Drop>>", self._on_drop)
        self.dnd_bind("<<DragEnter>>", self._on_drag_enter)
        self.dnd_bind("<<DragLeave>>", self._on_drag_leave)

        # 終了確認
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # CLI引数
        if cli_path is not None:
            self._load_archive(cli_path)

        if cli_compress_path is not None:
            self._compress_sources = [cli_compress_path]
            self._compress_no_dialog = True
            self.after_idle(self._start_compress_flow)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # --- アーカイブ選択 ---
        file_frame = ctk.CTkFrame(self, corner_radius=12)
        file_frame.grid(row=0, column=0, padx=20, pady=(18, 6), sticky="ew")
        file_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            file_frame,
            text="アーカイブ",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, padx=(16, 8), pady=12, sticky="w")

        self._path_var = ctk.StringVar()
        self._path_entry = ctk.CTkEntry(
            file_frame,
            textvariable=self._path_var,
            state="readonly",
            height=36,
        )
        self._path_entry.grid(row=0, column=1, padx=4, pady=12, sticky="ew")
        self._browse_btn = ctk.CTkButton(
            file_frame, text="開く", width=80, height=36, command=self._on_browse
        )
        self._browse_btn.grid(row=0, column=2, padx=(4, 8), pady=12)

        self._settings_btn = ctk.CTkButton(
            file_frame,
            text="設定",
            width=90,
            height=36,
            command=self._on_open_settings,
        )
        self._settings_btn.grid(row=0, column=3, padx=(0, 4), pady=12)

        self._recent_var = ctk.StringVar(value="最近のファイル")
        self._recent_menu = ctk.CTkOptionMenu(
            file_frame,
            values=["最近のファイル"],
            variable=self._recent_var,
            width=120,
            command=self._on_recent_selected,
        )
        self._recent_menu.grid(row=0, column=4, padx=(0, 16), pady=12)

        # --- ドロップゾーン (未選択時) ---
        self._drop_frame = ctk.CTkFrame(
            self, border_width=1, border_color=_DROP_BORDER_COLOR, corner_radius=12
        )
        self._drop_frame.grid(row=1, column=0, padx=20, pady=6, sticky="nsew")
        self._drop_frame.grid_rowconfigure(0, weight=1)
        self._drop_frame.grid_columnconfigure(0, weight=1)

        self._drop_label = ctk.CTkLabel(
            self._drop_frame,
            text="アーカイブファイルをここにドラッグ&ドロップ\nまたは「開く」ボタンで選択",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="gray",
        )
        self._drop_label.grid(row=0, column=0, sticky="nsew")

        # --- ファイル一覧 (読込後) ---
        self._list_frame = ctk.CTkFrame(self, corner_radius=12)
        self._list_frame.grid_rowconfigure(1, weight=1)
        self._list_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self._list_frame, text="内容:").grid(
            row=0, column=0, padx=(8, 2), pady=(8, 2), sticky="w"
        )

        self._search_var = ctk.StringVar()
        self._search_entry = ctk.CTkEntry(
            self._list_frame,
            textvariable=self._search_var,
            placeholder_text="絞り込み...",
            height=24,
        )
        self._search_entry.grid(row=0, column=1, padx=(2, 8), pady=(6, 0), sticky="ew")
        self._search_entry.bind("<KeyRelease>", self._on_search_keyrelease)

        tree_frame = ctk.CTkFrame(self._list_frame)
        tree_frame.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="nsew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        columns = ("#", "name", "size", "compressed", "date")
        self._tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", height=12
        )
        self._tree.heading("#", text="#")
        self._tree.heading("name", text="名前")
        self._tree.heading("size", text="サイズ")
        self._tree.heading("compressed", text="圧縮後")
        self._tree.heading("date", text="更新日時")
        self._tree.column("#", width=35, minwidth=30, stretch=False, anchor="e")
        self._tree.column("name", width=280, minwidth=160, stretch=True)
        self._tree.column("size", width=80, minwidth=60, stretch=False)
        self._tree.column("compressed", width=80, minwidth=60, stretch=False)
        self._tree.column("date", width=130, minwidth=90, stretch=False)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        # --- プレビュー ---
        self._preview_frame = ctk.CTkFrame(self._list_frame)
        self._preview_label = ctk.CTkLabel(
            self._preview_frame,
            text="",
            anchor="w",
            justify="left",
            font=ctk.CTkFont(size=12),
        )
        self._preview_label.pack(fill="both", expand=True, padx=8, pady=4)

        # --- 展開先 ---
        dest_frame = ctk.CTkFrame(self, corner_radius=12)
        dest_frame.grid(row=2, column=0, padx=20, pady=6, sticky="ew")
        dest_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(dest_frame, text="展開先:").grid(
            row=0, column=0, padx=(8, 4), pady=8, sticky="w"
        )
        self._dest_var = ctk.StringVar()
        self._dest_entry = ctk.CTkEntry(
            dest_frame, textvariable=self._dest_var, state="readonly"
        )
        self._dest_entry.grid(row=0, column=1, padx=4, pady=8, sticky="ew")
        self._dest_btn = ctk.CTkButton(
            dest_frame, text="参照", width=80, command=self._on_dest_browse
        )
        self._dest_btn.grid(row=0, column=2, padx=(4, 8), pady=8)

        # --- キュー情報 ---
        self._queue_label = ctk.CTkLabel(
            dest_frame,
            text="",
            anchor="w",
        )
        self._queue_label.grid(
            row=1, column=0, columnspan=3, padx=8, pady=(0, 4), sticky="w"
        )

        # --- プログレスバー＆ボタン ---
        bottom_frame = ctk.CTkFrame(self, corner_radius=12)
        bottom_frame.grid(row=3, column=0, padx=20, pady=(6, 18), sticky="ew")
        bottom_frame.grid_columnconfigure(2, weight=1)

        self._progress = ctk.CTkProgressBar(bottom_frame, mode="determinate")
        self._progress.grid(
            row=0, column=0, columnspan=5, padx=8, pady=(8, 4), sticky="ew"
        )
        self._progress.set(0)
        self._progress.grid_remove()

        self._open_on_done_var = ctk.BooleanVar(value=True)
        self._open_check = ctk.CTkCheckBox(
            bottom_frame,
            text="完了後にフォルダを開く",
            variable=self._open_on_done_var,
            onvalue=True,
            offvalue=False,
        )
        self._open_check.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="w")

        self._close_on_done_var = ctk.BooleanVar(value=False)
        self._close_check = ctk.CTkCheckBox(
            bottom_frame,
            text="完了後に閉じる",
            variable=self._close_on_done_var,
            onvalue=True,
            offvalue=False,
        )
        self._close_check.grid(row=1, column=1, padx=(0, 8), pady=(0, 8), sticky="w")

        self._cancel_btn = ctk.CTkButton(
            bottom_frame,
            text="キャンセル",
            width=80,
            height=36,
            command=self._on_cancel,
        )
        self._cancel_btn.grid(row=2, column=0, padx=(8, 4), pady=(0, 8), sticky="w")
        self._cancel_btn.grid_remove()

        self._status_var = ctk.StringVar(value="ファイルを選択してください")
        self._status_label = ctk.CTkLabel(
            bottom_frame, textvariable=self._status_var, anchor="w"
        )
        self._status_label.grid(
            row=2, column=1, columnspan=2, padx=4, pady=(0, 8), sticky="w"
        )

        self._compress_btn = ctk.CTkButton(
            bottom_frame,
            text="圧縮する",
            width=100,
            height=36,
            command=self._on_compress,
        )
        self._compress_btn.grid(row=2, column=3, padx=(4, 4), pady=(0, 8), sticky="e")

        self._extract_btn = ctk.CTkButton(
            bottom_frame,
            text="解凍する",
            width=100,
            height=36,
            command=self._on_extract,
            state="disabled",
        )
        self._extract_btn.grid(row=2, column=4, padx=(4, 8), pady=(0, 8), sticky="e")

        self._extract_btn.grid_remove()

    @staticmethod
    def _resolve_mode() -> bool:
        mode = ctk.get_appearance_mode().lower()
        if mode == "system":
            try:
                import darkdetect

                return bool(darkdetect.isDark())
            except ImportError:
                return False
        return mode == "dark"

    def _apply_tree_style(self) -> None:
        is_dark = self._resolve_mode()
        style = ttk.Style()
        if is_dark:
            style.theme_use("clam")
            style.configure(
                "Treeview",
                background="#2b2b2b",
                foreground="#dce4ee",
                fieldbackground="#2b2b2b",
                borderwidth=0,
            )
            style.configure(
                "Treeview.Heading",
                background="#333333",
                foreground="#dce4ee",
                relief="flat",
            )
            style.map(
                "Treeview",
                background=[("selected", "#1f538d")],
                foreground=[("selected", "#ffffff")],
            )
            style.map(
                "Treeview.Heading",
                background=[("active", "#404040")],
            )
        else:
            style.theme_use("clam")
            style.configure(
                "Treeview",
                background="#ffffff",
                foreground="#000000",
                fieldbackground="#ffffff",
                borderwidth=0,
            )
            style.configure(
                "Treeview.Heading",
                background="#f0f0f0",
                foreground="#000000",
                relief="flat",
            )
            style.map(
                "Treeview",
                background=[("selected", "#e5f3ff")],
                foreground=[("selected", "#000000")],
            )
            style.map(
                "Treeview.Heading",
                background=[("active", "#e0e0e0")],
            )

    def _start_theme_poll(self) -> None:
        self._stop_theme_poll()
        if ctk.get_appearance_mode().lower() != "system":
            return
        self._tree_last_dark = self._resolve_mode()
        self._tree_poll_id = self.after(2000, self._poll_appearance_mode)

    def _stop_theme_poll(self) -> None:
        if self._tree_poll_id is not None:
            self.after_cancel(self._tree_poll_id)
            self._tree_poll_id = None

    def _poll_appearance_mode(self) -> None:
        is_dark = self._resolve_mode()
        if is_dark != self._tree_last_dark:
            self._tree_last_dark = is_dark
            self._apply_tree_style()
        self._tree_poll_id = self.after(2000, self._poll_appearance_mode)

    # ---- イベントハンドラ ----

    def _on_theme_changed(self, mode: str) -> None:
        ctk.set_appearance_mode(mode)
        self._apply_tree_style()
        self._start_theme_poll()
        self._settings.set("theme", mode)

    def _on_open_settings(self) -> None:
        SettingsDialog(
            parent=self,
            settings=self._settings,
            on_theme_changed=self._on_theme_changed,
        )

    def _on_recent_selected(self, display_name: str) -> None:
        if display_name == "最近のファイル":
            return
        real_path = self._recent_display_to_path.get(display_name)
        if real_path is None:
            return
        path = Path(real_path)
        if not path.exists():
            # 存在しない履歴を除去
            self._remove_missing_recent(real_path)
            self._refresh_recent_menu()
            self._show_error("ファイルが見つかりません", f"{real_path} は存在しません")
            return
        self._load_archive(path)

    def _remove_missing_recent(self, path: str) -> None:
        recent = self._settings.get("recent_files", [])
        if path in recent:
            recent.remove(path)
            self._settings.set("recent_files", recent)

    def _refresh_recent_menu(self) -> None:
        files = self._settings.get("recent_files", [])
        if not files:
            self._recent_menu.configure(values=["最近のファイル"])
            self._recent_var.set("最近のファイル")
            return
        self._recent_display_to_path.clear()
        display_files = []
        for f in files:
            display = _truncate_path(f)
            if display in self._recent_display_to_path:
                display = f"{display} ({f})"
            self._recent_display_to_path[display] = f
            display_files.append(display)
        # 「履歴を削除」を追加
        display_files.append("履歴を削除")
        self._recent_menu.configure(values=display_files)
        self._recent_var.set(
            display_files[0] if len(display_files) == 1 else "最近のファイル"
        )

    def _on_drag_enter(self, _event: object = None) -> None:
        self._highlight_drop(True)

    def _on_drag_leave(self, _event: object = None) -> None:
        self._highlight_drop(False)

    def _highlight_drop(self, highlight: bool) -> None:
        color = _DROP_HIGHLIGHT_COLOR if highlight else _DROP_BORDER_COLOR
        try:
            self._drop_frame.configure(border_color=color)
        except AttributeError:
            pass

    def _on_drop(self, event: object) -> None:
        """ドラッグ&ドロップでファイルを受け取る"""
        raw = getattr(event, "data", "")
        if not raw:
            return
        paths = [p.strip("{}") for p in re.findall(r"\{[^}]+\}|\S+", raw)]

        archive_paths: list[Path] = []
        compress_candidates: list[Path] = []
        unsupported_count = 0
        nonexistent_count = 0
        duplicate_count = 0

        seen = set()
        for p in paths:
            path = Path(p)
            if not path.exists():
                nonexistent_count += 1
                continue
            resolved = path.resolve()
            if resolved in seen:
                duplicate_count += 1
                continue
            seen.add(resolved)

            if self._archive_service.is_supported(path):
                archive_paths.append(path)
            else:
                compress_candidates.append(path)
                unsupported_count += 1

        # 結果表示
        messages = []
        if nonexistent_count > 0:
            messages.append(f"{nonexistent_count}個のファイルが存在しません")
        if duplicate_count > 0:
            messages.append(f"{duplicate_count}個の重複を除外")
        if unsupported_count > 0:
            messages.append(
                f"{unsupported_count}個の非対応ファイルは圧縮候補になります"
            )
        if archive_paths:
            messages.append(f"{len(archive_paths)}個のアーカイブをキューに追加")

        if not archive_paths and not compress_candidates:
            self._show_error(
                "ファイルを追加できません",
                "; ".join(messages) if messages else "すべてのファイルが無効です",
            )
            return

        # アーカイブが1つも読み込まれていない場合、最初の1つを読み込む
        if self._current_archive_path is None and archive_paths:
            self._load_archive(archive_paths.pop(0))

        # 残りのアーカイブをキューに追加
        for arch in archive_paths:
            if arch not in self._archive_queue:
                self._archive_queue.append(arch)

        # キュー状態更新
        self._update_queue_status()

        # 非アーカイブ → 圧縮候補
        if compress_candidates and self._current_archive_path is None:
            self._compress_sources = compress_candidates
            self._status_var.set(
                f"{len(compress_candidates)}個のファイルを圧縮できます"
            )
            self._start_compress_flow()

        if messages:
            self._show_info("ドロップ結果", "\n".join(messages))

    def _on_browse(self) -> None:
        path = filedialog.askopenfilename(
            title="アーカイブファイルを選択",
            filetypes=[
                ("アーカイブ", "*.zip *.rar *.7z"),
                ("ZIP", "*.zip"),
                ("RAR", "*.rar"),
                ("7z", "*.7z"),
                ("すべてのファイル", "*.*"),
            ],
        )
        if not path:
            return
        self._load_archive(Path(path))

    def _update_queue_status(self) -> None:
        q = len(self._archive_queue)
        if q > 0:
            self._queue_label.configure(text=f"キュー: {q}個のアーカイブ待機")
        else:
            self._queue_label.configure(text="")

    def _load_archive(self, path: Path) -> None:
        """アーカイブを読み込んで内容一覧を表示"""
        password = self._get_password_for(path)
        info = None
        for attempt in range(3):
            try:
                info = self._archive_service.list_archive(path, password=password)
                break
            except (PasswordRequiredError, InvalidPasswordError):
                self._mark_password_failed(path)
                password = (
                    self._show_password_error(path.name)
                    if attempt > 0
                    else self._ask_password(path.name)
                )
                if password is None:
                    self._status_var.set("アーカイブの読み込みをキャンセルしました")
                    return
                self._set_password_for(path, password)
            except ArchiveError as exc:
                self._entries = []
                self._is_encrypted = False
                self._status_var.set(f"エラー: {exc.user_message()}")
                self._refresh_tree()
                self._show_drop_zone()
                self._extract_btn.configure(state="disabled")
                return
            except Exception as exc:
                self._entries = []
                self._is_encrypted = False
                self._status_var.set(f"エラー: ファイルを開けませんでした ({exc})")
                self._refresh_tree()
                self._show_drop_zone()
                self._extract_btn.configure(state="disabled")
                return

        if info is None:
            self._show_error(
                "パスワードが正しくありません",
                f"{path.name}: パスワードを複数回試行しましたが開けませんでした",
            )
            return

        self._entries = info.entries
        self._is_encrypted = info.is_encrypted
        self._cleanup_temp_dir()
        self._current_archive_path = path
        if path not in self._archive_queue:
            self._archive_queue.append(path)
        else:
            self._archive_queue.remove(path)
            self._archive_queue.insert(0, path)

        self._search_var.set("")
        self._path_var.set(str(path))
        self._settings.add_recent_file(str(path))
        self._refresh_recent_menu()
        self._update_dest_display()

        total_size = sum(entry.size for entry in self._entries)
        self._refresh_tree()
        self._show_file_list()
        self._compress_btn.grid_remove()
        self._extract_btn.grid()
        self._extract_btn.configure(state="normal")
        self._status_var.set(
            f"{len(self._entries)} 個のエントリ ({_format_size(total_size)})"
            + (" (パスワード保護)" if self._is_encrypted else "")
        )
        self._update_queue_status()

    def _update_dest_display(self) -> None:
        """展開先の基準ディレクトリを表示する。"""
        if self._current_archive_path is None:
            return
        self._dest_var.set(str(self._current_archive_path.parent))

    def _refresh_tree(self) -> None:
        for row in self._tree.get_children():
            self._tree.delete(row)
        query = self._search_var.get().strip().lower()
        filtered = (
            [e for e in self._entries if not query or query in e.name.lower()]
            if query
            else self._entries
        )
        rows = [
            (
                i,
                e.name,
                _format_size(e.size),
                _format_size(e.compressed_size),
                e.modified.strftime("%Y-%m-%d %H:%M"),
            )
            for i, e in enumerate(filtered, start=1)
        ]
        for values in rows:
            self._tree.insert("", "end", values=values)

    def _on_tree_select(self, _event: object = None) -> None:
        if self._current_archive_path is None:
            return
        sel = self._tree.selection()
        if not sel:
            return
        values = self._tree.item(sel[0], "values")
        if not values or len(values) < 2:
            return
        entry_name: str = values[1]
        self._show_preview(entry_name)

    def _on_search_keyrelease(self, _event: object = None) -> None:
        self._refresh_tree()

    def _show_preview(self, name: str) -> None:
        self._preview_frame.grid_forget()
        self._preview_label.configure(text="")
        self._current_image = None

        # サイズ上限チェック
        entry = None
        for e in self._entries:
            if e.name == name:
                entry = e
                break
        if entry is not None and entry.size > _MAX_PREVIEW_FILE_SIZE:
            self._preview_label.configure(
                text=f"ファイルが大きすぎてプレビューできません ({_format_size(entry.size)})"
            )
            self._preview_frame.grid(row=2, column=0, padx=8, pady=(0, 4), sticky="ew")
            return

        ext = Path(name).suffix.lower()
        if ext in _TEXT_EXTENSIONS:
            self._preview_text(name)
        elif ext in _IMAGE_EXTENSIONS:
            self._preview_image(name)
        else:
            self._preview_label.configure(text="プレビュー不可")
            self._preview_frame.grid(row=2, column=0, padx=8, pady=(0, 4), sticky="ew")

    def _preview_text(self, name: str) -> None:
        assert self._current_archive_path is not None
        try:
            data = self._archive_service.read_entry(
                self._current_archive_path,
                name,
                password=self._get_password_for(self._current_archive_path),
            )
        except Exception:
            self._preview_label.configure(text="プレビューを読み込めませんでした")
            self._preview_frame.grid(row=2, column=0, padx=8, pady=(0, 4), sticky="ew")
            return

        if data is None:
            self._preview_label.configure(text="プレビューを読み込めませんでした")
            self._preview_frame.grid(row=2, column=0, padx=8, pady=(0, 4), sticky="ew")
            return

        text = _decode_text(data)
        self._preview_label.configure(text=text)
        self._preview_frame.grid(row=2, column=0, padx=8, pady=(0, 4), sticky="ew")

    def _preview_image(self, name: str) -> None:
        assert self._current_archive_path is not None
        try:
            data = self._archive_service.read_entry(
                self._current_archive_path,
                name,
                password=self._get_password_for(self._current_archive_path),
            )
        except Exception:
            self._preview_label.configure(text="画像をプレビューできません")
            self._preview_frame.grid(row=2, column=0, padx=8, pady=(0, 4), sticky="ew")
            return

        if data is None:
            self._preview_label.configure(text="画像をプレビューできません")
            self._preview_frame.grid(row=2, column=0, padx=8, pady=(0, 4), sticky="ew")
            return

        try:
            img = Image.open(io.BytesIO(data))
            max_size = (400, 250)
            img.thumbnail(max_size)
            ctk_img = ctk.CTkImage(img, size=img.size)
            self._preview_label.configure(image=ctk_img, text="")
            self._current_image = ctk_img
        except Exception:
            self._preview_label.configure(text="画像をプレビューできません")
            self._preview_frame.grid(row=2, column=0, padx=8, pady=(0, 4), sticky="ew")
            return
        self._preview_frame.grid(row=2, column=0, padx=8, pady=(0, 4), sticky="ew")

    def _show_drop_zone(self) -> None:
        self._list_frame.grid_forget()
        self._drop_frame.grid(row=1, column=0, padx=12, pady=4, sticky="nsew")
        self._compress_btn.grid()
        self._compress_btn.configure(state="normal")
        self._extract_btn.grid_remove()
        self._extract_btn.configure(state="disabled")

    def _show_file_list(self) -> None:
        self._drop_frame.grid_forget()
        self._list_frame.grid(row=1, column=0, padx=12, pady=4, sticky="nsew")

    def _on_dest_browse(self) -> None:
        path = filedialog.askdirectory(title="展開先フォルダを選択")
        if path:
            self._dest_var.set(path)
            self._settings.set("last_dest", path)

    def _cleanup_temp_dir(self) -> None:
        if self._temp_dir is not None:
            try:
                self._temp_dir.cleanup()
            except (PermissionError, OSError):
                pass
            self._temp_dir = None

    # ---- パスワード管理 ----

    def _get_password_for(self, path: Path) -> Optional[str]:
        return self._passwords.get(str(path))

    def _set_password_for(self, path: Path, password: str) -> None:
        self._passwords[str(path)] = password
        self._failed_passwords.discard(str(path))

    def _mark_password_failed(self, path: Path) -> None:
        self._failed_passwords.add(str(path))
        self._passwords.pop(str(path), None)

    def _clear_passwords(self) -> None:
        self._passwords.clear()
        self._failed_passwords.clear()

    def _ask_password(self, archive_name: str) -> Optional[str]:
        dialog = ctk.CTkInputDialog(
            title="パスワード",
            text=f"「{archive_name}」はパスワードで保護されています\nパスワードを入力してください:",
        )
        result = dialog.get_input()
        return result if result else None

    def _show_password_error(self, archive_name: str) -> Optional[str]:
        dialog = ctk.CTkInputDialog(
            title="パスワードが正しくありません",
            text=f"「{archive_name}」のパスワードが正しくありません\n再入力してください:",
        )
        result = dialog.get_input()
        if result:
            return result
        return None

    def _request_password_from_worker(
        self, archive_name: str, *, retry: bool = False
    ) -> Optional[str]:
        """メインスレッドのダイアログ結果をキャンセル可能に待機する。"""
        completed = Event()
        result: list[Optional[str]] = [None]

        def ask() -> None:
            try:
                result[0] = (
                    self._show_password_error(archive_name)
                    if retry
                    else self._ask_password(archive_name)
                )
            finally:
                completed.set()

        self.after(0, ask)
        while not completed.wait(0.1):
            if self._archive_service.is_cancelled():
                return None
        return result[0]

    # ---- 展開処理 ----

    def _on_extract(self) -> None:
        if self._is_busy or not self._archive_queue:
            return

        self._is_busy = True
        self._archive_service.reset_cancel()
        self._set_ui_enabled(False)
        self._show_cancel_button(True)
        self._progress.set(0)
        self._progress.grid()

        paths_copy = list(self._archive_queue)
        destination_text = self._dest_var.get().strip()
        base_destination = (
            Path(destination_text) if destination_text else paths_copy[0].parent
        )
        self._status_var.set(f"解凍開始: {len(paths_copy)}個のアーカイブ")

        self._worker_thread = Thread(
            target=self._do_batch_extract,
            args=(paths_copy, base_destination),
            daemon=False,
        )
        self._worker_thread.start()

    def _do_batch_extract(self, paths: list[Path], base_destination: Path) -> None:
        """バックグラウンドでバッチ展開を実行する。"""
        success_count = 0
        fail_count = 0
        total_archives = len(paths)

        for index, archive_path in enumerate(paths):
            if self._archive_service.is_cancelled():
                self.after(
                    0, lambda count=success_count: self._on_extract_cancelled(count)
                )
                return

            archive_name = archive_path.name
            try:
                self.after(
                    0,
                    lambda i=index + 1, total=total_archives, name=archive_name: (
                        self._status_var.set(f"[{i}/{total}] {name} を解凍中...")
                    ),
                )

                password = self._get_password_for(archive_path)
                info = None
                for attempt in range(3):
                    try:
                        info = self._archive_service.list_archive(
                            archive_path, password=password
                        )
                        break
                    except (PasswordRequiredError, InvalidPasswordError):
                        self._mark_password_failed(archive_path)
                        password = self._request_password_from_worker(
                            archive_name, retry=attempt > 0
                        )
                        if password is None:
                            break
                        self._set_password_for(archive_path, password)

                if info is None:
                    if self._archive_service.is_cancelled():
                        self.after(
                            0,
                            lambda count=success_count: self._on_extract_cancelled(
                                count
                            ),
                        )
                        return
                    fail_count += 1
                    continue

                archive_destination = ArchiveService.resolve_extract_dest(
                    base_destination, archive_path, info.entries
                )

                if password is None and info.is_encrypted:
                    password = self._request_password_from_worker(archive_name)
                    if password is None:
                        fail_count += 1
                        continue
                    self._set_password_for(archive_path, password)

                def make_progress(
                    archive_index: int = index,
                    current_archive: str = archive_name,
                    archive_total: int = total_archives,
                ):
                    last_poll = [0.0]

                    def on_progress(current: int, total: int, name: str = "") -> None:
                        if self._archive_service.is_cancelled():
                            raise CancelledError(str(archive_path))
                        now = time.monotonic()
                        if now - last_poll[0] < 0.1 and current < total:
                            return
                        last_poll[0] = now
                        percentage = current / max(total, 1)
                        self.after(
                            0, lambda value=percentage: self._progress.set(value)
                        )
                        name_part = f" - {name}" if name else ""
                        self.after(
                            0,
                            lambda: self._status_var.set(
                                f"[{archive_index + 1}/{archive_total}] "
                                f"{current_archive}: {percentage:.0%} "
                                f"({current}/{total}){name_part}"
                            ),
                        )

                    return on_progress

                for attempt in range(3):
                    try:
                        self._archive_service.extract(
                            archive_path,
                            ExtractionOptions(
                                dest_dir=archive_destination,
                                password=password,
                                on_progress=make_progress(),
                            ),
                        )
                        success_count += 1
                        break
                    except (PasswordRequiredError, InvalidPasswordError):
                        self._mark_password_failed(archive_path)
                        if attempt >= 2:
                            fail_count += 1
                            self.after(
                                0,
                                lambda name=archive_name: self._show_error(
                                    "パスワードが正しくありません",
                                    f"{name}: パスワードを複数回試行しましたが展開できませんでした",
                                ),
                            )
                            break
                        password = self._request_password_from_worker(
                            archive_name, retry=True
                        )
                        if password is None:
                            fail_count += 1
                            break
                        self._set_password_for(archive_path, password)
                    except ArchiveBombError as exc:
                        fail_count += 1
                        self.after(
                            0,
                            lambda name=archive_name, message=str(exc): (
                                self._show_error(
                                    "安全のため展開を中止しました", f"{name}: {message}"
                                )
                            ),
                        )
                        break
                    except UnsafeArchiveError as exc:
                        fail_count += 1
                        self.after(
                            0,
                            lambda name=archive_name, message=str(exc): (
                                self._show_error(
                                    "安全でないエントリを検出しました",
                                    f"{name}: {message}",
                                )
                            ),
                        )
                        break
                    except ExternalToolNotFoundError:
                        fail_count += 1
                        self.after(
                            0,
                            lambda: self._show_error(
                                "展開エンジンが見つかりません",
                                "同梱7-Zipが利用できません。kaitoを再インストールしてください。",
                            ),
                        )
                        break
                    except CancelledError:
                        self.after(
                            0,
                            lambda count=success_count: self._on_extract_cancelled(
                                count
                            ),
                        )
                        return
                    except ArchiveError as exc:
                        fail_count += 1
                        self.after(
                            0,
                            lambda name=archive_name, message=exc.user_message(): (
                                self._show_error(
                                    "展開に失敗しました", f"{name}: {message}"
                                )
                            ),
                        )
                        break
            except CancelledError:
                self.after(
                    0, lambda count=success_count: self._on_extract_cancelled(count)
                )
                return
            except Exception as exc:
                fail_count += 1
                self.after(
                    0,
                    lambda name=archive_name, message=str(exc): self._show_error(
                        "展開に失敗しました", f"{name}: {message}"
                    ),
                )

        self.after(0, lambda: self._on_extract_done(success_count, fail_count))

    def _on_extract_done(self, success: int, fail: int) -> None:
        self._worker_thread = None
        self._is_busy = False
        self._show_cancel_button(False)
        self._set_ui_enabled(True)
        self._progress.grid_remove()

        if fail > 0:
            self._status_var.set(f"解凍: {success}成功, {fail}失敗")
        else:
            self._status_var.set(f"解凍完了 ({success}ファイル)")

        dest = Path(self._dest_var.get()) if self._dest_var.get() else Path.cwd()

        # 設定保存
        self._settings.set("open_on_done", self._open_on_done_var.get())
        self._settings.set("close_on_done", self._close_on_done_var.get())
        self._settings.set("last_dest", str(dest))

        if self._open_on_done_var.get() and success > 0:
            self._open_folder(dest)

        self._archive_queue.clear()
        self._current_archive_path = None
        self._entries = []
        self._clear_passwords()
        self._update_queue_status()
        self._show_drop_zone()

        if self._close_on_done_var.get() and fail == 0:
            self.after(500, self.destroy)

    def _on_extract_cancelled(self, success: int) -> None:
        self._worker_thread = None
        self._is_busy = False
        self._show_cancel_button(False)
        self._set_ui_enabled(True)
        self._progress.set(0)
        self._progress.grid_remove()
        self._status_var.set(f"解凍をキャンセルしました ({success}ファイル完了)")
        self._show_drop_zone()

    def _on_cancel(self) -> None:
        self._archive_service.cancel()
        self._status_var.set("キャンセル中...")

    def _show_cancel_button(self, show: bool) -> None:
        if show:
            self._cancel_btn.grid()
        else:
            self._cancel_btn.grid_remove()

    def _set_ui_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self._browse_btn.configure(state=state)
        self._dest_btn.configure(state=state)
        self._extract_btn.configure(state=state)
        self._compress_btn.configure(state=state)
        self._recent_menu.configure(state=state)

    def _open_folder(self, path: Path) -> None:
        if sys.platform == "win32":
            try:
                subprocess.Popen(["explorer", str(path)])
            except OSError:
                pass

    def _show_error(self, title: str, message: str) -> None:
        """ユーザー向けエラーダイアログ"""
        messagebox.showerror(title=title, message=message)

    def _show_info(self, title: str, message: str) -> None:
        """情報ダイアログ"""
        messagebox.showinfo(title=title, message=message)

    # ---- 終了処理 ----

    def _on_close(self) -> None:
        if self._closing:
            return
        if self._is_busy:
            result = messagebox.askyesno(
                title="確認",
                message="処理中です。中断して終了しますか？",
            )
            if not result:
                return
            self._closing = True
            self._archive_service.cancel()
            self._status_var.set("処理を中断して終了しています...")
            self._wait_for_worker_then_destroy()
            return
        self._closing = True
        self._cleanup_temp_dir()
        self.destroy()

    def _wait_for_worker_then_destroy(self) -> None:
        worker = self._worker_thread
        if worker is not None and worker.is_alive():
            self.after(100, self._wait_for_worker_then_destroy)
            return
        self._cleanup_temp_dir()
        self.destroy()

    # ---- 圧縮機能 ----

    def _on_compress(self) -> None:
        paths = filedialog.askopenfilenames(title="圧縮するファイルを選択")
        if paths:
            self._compress_sources = [Path(p) for p in paths]
            self._start_compress_flow()
            return
        folder = filedialog.askdirectory(title="圧縮するフォルダを選択")
        if folder:
            self._compress_sources = [Path(folder)]
            self._start_compress_flow()

    def _start_compress_flow(self) -> None:
        if not self._compress_sources:
            return

        if self._compress_no_dialog:
            first = self._compress_sources[0]
            output = first.parent / (first.stem + ".zip")
            self._start_compress(output)
            return

        first = self._compress_sources[0]
        default_name = first.stem + ".zip"
        default_dir = str(first.parent) if first.parent != Path() else "."
        output = filedialog.asksaveasfilename(
            title="圧縮ファイルの保存先",
            initialdir=default_dir,
            defaultextension=".zip",
            initialfile=default_name,
            filetypes=[
                ("ZIP", "*.zip"),
                ("7z", "*.7z"),
            ],
        )
        if not output:
            return

        output_path = Path(output)
        if output_path.suffix.lower() == ".rar":
            self._show_error(
                "非対応の形式",
                "RAR形式の作成はライセンス上の制約により対応していません。\n"
                "ZIP形式または7z形式を選択してください。",
            )
            return

        self._start_compress(output_path)

    def _start_compress(self, output: Path) -> None:
        """圧縮開始（共通エントリ）"""
        ext = output.suffix.lower()
        if not self._archive_service.is_creation_supported(output):
            self._show_error(
                "未対応の形式", f"{ext} 形式の作成はサポートされていません"
            )
            return

        # 自己包含チェック
        error = ArchiveService.check_self_contained(self._compress_sources, output)
        if error:
            self._show_error("圧縮対象にエラー", error)
            return

        self._is_busy = True
        self._archive_service.reset_cancel()
        self._set_ui_enabled(False)
        self._show_cancel_button(True)
        self._progress.set(0)
        self._progress.grid()

        self._worker_thread = Thread(
            target=self._do_compress,
            args=(list(self._compress_sources), output),
            daemon=False,
        )
        self._worker_thread.start()

    def _do_compress(self, sources: list[Path], output: Path) -> None:
        """バックグラウンド圧縮"""
        temp_dir: Optional[str] = None
        temp_output: Optional[Path] = None
        try:
            import os as os_mod

            temp_dir = tempfile.mkdtemp(prefix="kaito_zip_", dir=output.parent)
            temp_output = Path(temp_dir) / output.name

            def on_progress(cur: int, total_: int, name: str = "") -> None:
                if self._archive_service.is_cancelled():
                    raise CancelledError(str(output))
                pct = cur / total_
                self.after(0, lambda p=pct: self._progress.set(p))
                self.after(
                    0,
                    lambda: self._status_var.set(
                        f"圧縮中: {pct:.0%} ({cur}/{total_}) - {name}"
                    ),
                )

            compression_level = self._settings.get("compression_level", 1)
            if (
                not isinstance(compression_level, int)
                or not 0 <= compression_level <= 9
            ):
                compression_level = 1

            opts = CompressionOptions(
                sources=sources,
                output_path=temp_output,
                compression_level=compression_level,
                on_progress=on_progress,
            )

            self._archive_service.create(opts)

            if self._archive_service.is_cancelled():
                self._cleanup_temp(temp_output)
                self.after(0, lambda: self._on_compress_cancelled())
                return

            # 検証してリネーム (原子的な置換)
            temp_output.replace(output)
            self.after(0, self._on_compress_done)

        except CancelledError:
            if temp_output:
                self._cleanup_temp(temp_output)
            self.after(0, lambda: self._on_compress_cancelled())
        except Exception as exc:
            if temp_output:
                self._cleanup_temp(temp_output)
            msg = str(exc)
            self.after(0, lambda: self._on_compress_error(msg))
        finally:
            if temp_dir:
                try:
                    os_mod.rmdir(temp_dir)
                except (OSError, NameError):
                    pass

    def _cleanup_temp(self, path: Path) -> None:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass

    def _on_compress_done(self) -> None:
        self._worker_thread = None
        self._is_busy = False
        self._show_cancel_button(False)
        self._status_var.set("圧縮完了")
        self._progress.set(1)
        self._progress.grid_remove()
        self._compress_sources = []
        close_after = self._compress_no_dialog
        self._compress_no_dialog = False
        if close_after:
            self.after(500, self.destroy)
        else:
            self._set_ui_enabled(True)

    def _on_compress_cancelled(self) -> None:
        self._worker_thread = None
        self._is_busy = False
        self._show_cancel_button(False)
        self._status_var.set("圧縮をキャンセルしました")
        self._progress.set(0)
        self._progress.grid_remove()
        self._compress_sources = []
        self._compress_no_dialog = False
        self._set_ui_enabled(True)

    def _on_compress_error(self, msg: str) -> None:
        self._worker_thread = None
        self._is_busy = False
        self._show_cancel_button(False)
        # ユーザー向けメッセージ
        user_msg = msg
        if "ライセンス" in msg:
            user_msg = "RAR形式の作成はライセンス上の制約により対応していません。ZIP形式をご利用ください。"
        self._status_var.set(f"エラー: {user_msg}")
        self._progress.set(0)
        self._progress.grid_remove()
        if self._compress_no_dialog:
            self._compress_no_dialog = False
            self.after(2000, self.destroy)
        else:
            self._set_ui_enabled(True)


def _decode_text(data: bytes, max_chars: int = _MAX_PREVIEW_CHARS) -> str:
    """バイトデータをテキストにデコード (UTF-8優先)"""
    try:
        return data.decode("utf-8")[:max_chars]
    except UnicodeDecodeError:
        pass
    try:
        return data.decode(locale.getencoding())[:max_chars]
    except (UnicodeDecodeError, LookupError):
        pass
    return data.decode("utf-8", errors="replace")[:max_chars]


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1024**2:
        return f"{size / 1024:.1f} KB"
    elif size < 1024**3:
        return f"{size / 1024**2:.1f} MB"
    else:
        return f"{size / 1024**3:.1f} GB"


def _truncate_path(path: str, max_len: int = 60) -> str:
    """長いパスを省略表示"""
    if len(path) <= max_len:
        return path
    p = Path(path)
    name = p.name
    if len(name) >= max_len - 3:
        return name[: max_len - 3] + "..."
    remain = max_len - len(name) - 3
    parent = str(p.parent)
    return "..." + parent[-(remain - 3) :] + "\\" + name


_CONTEXT_EXTENSIONS = [".zip", ".rar", ".7z"]


def _get_exe_path() -> Path:
    """kaito実行ファイルのパスを返す"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    dev_exe = Path(sys.executable).parent.parent / "dist" / "kaito.exe"
    if dev_exe.exists():
        return dev_exe
    return Path(sys.executable)


def install_context_menu() -> None:
    """Windowsコンテキストメニューにkaitoを登録"""
    try:
        from winreg import (  # type: ignore[attr-defined]
            CreateKeyEx,
            HKEY_CURRENT_USER,
            KEY_SET_VALUE,
            REG_SZ,
            SetValueEx,
        )
    except ImportError:
        return

    exe = _get_exe_path()
    exe_str = f'"{exe}"'
    base = r"Software\Classes"

    # 解凍: 対応拡張子のみ
    for ext in _CONTEXT_EXTENSIONS:
        key_path = f"{base}\\SystemFileAssociations\\{ext}\\shell\\kaito_extract"
        with CreateKeyEx(HKEY_CURRENT_USER, key_path, 0, KEY_SET_VALUE) as key:
            SetValueEx(key, None, 0, REG_SZ, "kaitoで解凍")
        cmd_path = f"{key_path}\\command"
        with CreateKeyEx(HKEY_CURRENT_USER, cmd_path, 0, KEY_SET_VALUE) as key:
            SetValueEx(key, None, 0, REG_SZ, f'{exe_str} "%1"')

    # 圧縮: ファイル・フォルダ
    for shell_root in [f"{base}\\*", f"{base}\\Directory"]:
        key_path = f"{shell_root}\\shell\\kaito_compress"
        with CreateKeyEx(HKEY_CURRENT_USER, key_path, 0, KEY_SET_VALUE) as key:
            SetValueEx(key, None, 0, REG_SZ, "kaitoで圧縮")
        cmd_path = f"{key_path}\\command"
        with CreateKeyEx(HKEY_CURRENT_USER, cmd_path, 0, KEY_SET_VALUE) as key:
            SetValueEx(key, None, 0, REG_SZ, f'{exe_str} --compress "%1"')

    print("コンテキストメニューを登録しました")


def _delete_key_recursive(root_key, sub_key: str) -> None:
    """レジストリキーをサブキーごと削除する"""
    try:
        from winreg import (  # type: ignore[attr-defined]
            DeleteKey,
            EnumKey,
            KEY_SET_VALUE,
            OpenKey,
            QueryInfoKey,
        )
    except ImportError:
        return
    try:
        with OpenKey(root_key, sub_key, 0, KEY_SET_VALUE) as key:
            info = QueryInfoKey(key)
            for _ in range(info[0]):
                child = EnumKey(key, 0)
                _delete_key_recursive(key, child)
        DeleteKey(root_key, sub_key)
    except (FileNotFoundError, OSError):
        pass


def uninstall_context_menu() -> None:
    """Windowsコンテキストメニューからkaitoを削除"""
    try:
        from winreg import HKEY_CURRENT_USER
    except ImportError:
        return
    base = r"Software\Classes"

    for ext in _CONTEXT_EXTENSIONS:
        _delete_key_recursive(
            HKEY_CURRENT_USER,
            f"{base}\\SystemFileAssociations\\{ext}\\shell\\kaito_extract",
        )

    for shell_root in [f"{base}\\*", f"{base}\\Directory"]:
        _delete_key_recursive(HKEY_CURRENT_USER, f"{shell_root}\\shell\\kaito_compress")

    print("コンテキストメニューを削除しました")


def _resolve_extract_dest(
    dest: Path, archive_path: Path, entries: list[ArchiveEntry]
) -> Path:
    """展開先を決定 (ArchiveServiceに委譲)"""
    return ArchiveService.resolve_extract_dest(dest, archive_path, entries)


def _read_archive_entry(
    archive_path: Path | str, name: str, cache_dir: str | None = None
) -> bytes:
    """アーカイブ内の1エントリを読み込む (互換性)"""
    _service = ArchiveService()
    result = _service.read_entry(archive_path, name)
    return result if result is not None else b""


def main() -> None:
    args = sys.argv[1:]

    if args and args[0] == "--install-context-menu":
        install_context_menu()
        return
    if args and args[0] == "--uninstall-context-menu":
        uninstall_context_menu()
        return

    settings = SettingsManager()
    ctk.set_appearance_mode(settings.get("theme", "system"))
    ctk.set_default_color_theme("blue")

    cli_path: Optional[Path] = None
    cli_compress_path: Optional[Path] = None

    service = ArchiveService()

    if args and args[0] == "--compress" and len(args) > 1:
        p = Path(args[1])
        if p.exists():
            cli_compress_path = p
    elif args:
        p = Path(args[0])
        if service.is_supported(p) and p.exists():
            cli_path = p

    app = UnzipApp(cli_path=cli_path, cli_compress_path=cli_compress_path)
    app.mainloop()


if __name__ == "__main__":
    main()
