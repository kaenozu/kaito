"""
src/kaito/gui/unzip_app.py
CustomTkinterを使用したZIP/RAR/7z解凍・圧縮GUIアプリ
ドラッグ&ドロップ対応 (tkinterdnd2)
関連: unzip.py (解凍/圧縮コアロジック), settings_dialog.py
"""

__version__ = "0.8.0"

import io
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from threading import Thread
from tkinter import filedialog, ttk
try:
    from winreg import (  # type: ignore[attr-defined]
        CreateKeyEx,
        DeleteKey,
        EnumKey,
        HKEY_CURRENT_USER,
        KEY_SET_VALUE,
        OpenKey,
        QueryInfoKey,
        REG_SZ,
        SetValueEx,
    )
except ImportError:  # pragma: no cover
    # Non-Windows: registry functions not available
    pass

from PIL import Image

import customtkinter as ctk
from tkinterdnd2 import TkinterDnD

from kaito.settings import SettingsManager
from kaito.unzip import (
    ZipEntry,
    create_archive,
    extract_archive,
    is_supported,
    list_archive,
)

from kaito.gui.settings_dialog import SettingsDialog

_DROP_BORDER_COLOR = "#3a7ebf"
_DROP_HIGHLIGHT_COLOR = "#1a6ebf"

_TEXT_EXTENSIONS = {".txt", ".md", ".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".yml", ".yaml", ".ini", ".cfg", ".log", ".csv", ".toml"}
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".ico"}
_MAX_PREVIEW_CHARS = 2000
_MAX_IMAGE_DIMENSION = (400, 250)


class UnzipApp(ctk.CTk, TkinterDnD.DnDWrapper):
    """ZIP解凍GUIメインウィンドウ"""

    def __init__(self, cli_path: Path | None = None, cli_compress_path: Path | None = None) -> None:
        super().__init__()

        self.TkdndVersion = TkinterDnD._require(self)

        self.title(f"kaito v{__version__}")
        self.geometry("800x520")
        self.minsize(600, 400)

        self._zip_path: Path | None = None
        self._archive_paths: list[Path] = []
        self._entries: list[ZipEntry] = []
        self._is_encrypted = False
        self._extracting = False
        self._temp_dir: tempfile.TemporaryDirectory | None = None
        self._current_image: ctk.CTkImage | None = None
        self._compress_sources: list[Path] = []
        self._compressing = False

        self._build_ui()

        self._settings = SettingsManager()

        self._tree_poll_id: str | None = None
        self._apply_tree_style()
        self._start_theme_poll()

        self._open_on_done_var.set(self._settings.get("open_on_done", True))

        self._refresh_recent_menu()

        # ウィンドウ全体をドロップターゲットに設定
        self.drop_target_register("*")
        self.dnd_bind("<<Drop>>", self._on_drop)
        self.dnd_bind("<<DragEnter>>", self._on_drag_enter)
        self.dnd_bind("<<DragLeave>>", self._on_drag_leave)

        # 起動時にファイルが渡されたら読み込む
        if cli_path is not None:
            self._load_archive(cli_path)

        # 起動時に圧縮対象が渡されたら圧縮フロー開始
        if cli_compress_path is not None:
            self._compress_sources = [cli_compress_path]
            self.after(100, self._start_compress_flow)

    def _build_ui(self) -> None:  # pragma: no cover
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # --- ZIPファイル選択 ---
        file_frame = ctk.CTkFrame(self)
        file_frame.grid(row=0, column=0, padx=12, pady=(12, 4), sticky="ew")
        file_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(file_frame, text="ZIPファイル:").grid(
            row=0, column=0, padx=(8, 4), pady=8, sticky="w"
        )
        self._path_var = ctk.StringVar()
        self._path_entry = ctk.CTkEntry(
            file_frame, textvariable=self._path_var, state="readonly"
        )
        self._path_entry.grid(row=0, column=1, padx=4, pady=8, sticky="ew")
        self._browse_btn = ctk.CTkButton(
            file_frame, text="参照", width=80, command=self._on_browse
        )
        self._browse_btn.grid(row=0, column=2, padx=(4, 8), pady=8)

        self._settings_btn = ctk.CTkButton(
            file_frame, text="設定", width=70, command=self._on_open_settings,
        )
        self._settings_btn.grid(row=0, column=3, padx=(0, 4), pady=8)

        self._recent_var = ctk.StringVar(value="最近のファイル")
        self._recent_menu = ctk.CTkOptionMenu(
            file_frame, values=["最近のファイル"],
            variable=self._recent_var, width=120,
            command=self._on_recent_selected,
        )
        self._recent_menu.grid(row=0, column=4, padx=(0, 8), pady=8)

        # --- ドロップゾーン (ZIP未選択時) ---
        self._drop_frame = ctk.CTkFrame(
            self, border_width=2, border_color=_DROP_BORDER_COLOR
        )
        self._drop_frame.grid(row=1, column=0, padx=12, pady=4, sticky="nsew")
        self._drop_frame.grid_rowconfigure(0, weight=1)
        self._drop_frame.grid_columnconfigure(0, weight=1)

        self._drop_label = ctk.CTkLabel(
            self._drop_frame,
            text="ZIP/RAR/7zファイルをここにドラッグ&ドロップ\nまたは「参照」ボタンで選択",
            font=ctk.CTkFont(size=20),
            text_color="gray",
        )
        self._drop_label.grid(row=0, column=0, sticky="nsew")

        # --- ファイル一覧 (ZIP読込後) ---
        self._list_frame = ctk.CTkFrame(self)
        self._list_frame.grid_rowconfigure(1, weight=1)
        self._list_frame.grid_columnconfigure(0, weight=0)
        self._list_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self._list_frame, text="内容:").grid(
            row=0, column=0, padx=(8, 2), pady=(8, 2), sticky="w"
        )

        self._search_var = ctk.StringVar()
        self._search_entry = ctk.CTkEntry(
            self._list_frame, textvariable=self._search_var,
            placeholder_text="絞り込み...", height=24,
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
            self._preview_frame, text="", anchor="w", justify="left",
            font=ctk.CTkFont(size=12),
        )
        self._preview_label.pack(fill="both", expand=True, padx=8, pady=4)

        # --- 展開先 ---
        dest_frame = ctk.CTkFrame(self)
        dest_frame.grid(row=2, column=0, padx=12, pady=4, sticky="ew")
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

        # --- プログレスバー＆ボタン ---
        bottom_frame = ctk.CTkFrame(self)
        bottom_frame.grid(row=3, column=0, padx=12, pady=(4, 12), sticky="ew")
        bottom_frame.grid_columnconfigure(2, weight=1)

        self._progress = ctk.CTkProgressBar(bottom_frame, mode="determinate")
        self._progress.grid(row=0, column=0, columnspan=4, padx=8, pady=(8, 4), sticky="ew")
        self._progress.set(0)
        self._progress.grid_remove()

        self._open_on_done_var = ctk.BooleanVar(value=True)
        self._open_check = ctk.CTkCheckBox(
            bottom_frame, text="完了後にフォルダを開く",
            variable=self._open_on_done_var, onvalue=True, offvalue=False,
        )
        self._open_check.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="w")

        self._status_var = ctk.StringVar(value="ファイルを選択してください")
        self._status_label = ctk.CTkLabel(
            bottom_frame, textvariable=self._status_var, anchor="w"
        )
        self._status_label.grid(row=2, column=0, columnspan=2, padx=8, pady=(0, 8), sticky="w")

        self._compress_btn = ctk.CTkButton(
            bottom_frame, text="圧縮", width=80, command=self._on_compress
        )
        self._compress_btn.grid(row=2, column=2, padx=(4, 4), pady=(0, 8), sticky="e")

        self._extract_btn = ctk.CTkButton(
            bottom_frame, text="解凍実行", command=self._on_extract, state="disabled"
        )
        self._extract_btn.grid(row=2, column=3, padx=(4, 8), pady=(0, 8), sticky="e")

    @staticmethod
    def _resolve_mode() -> bool:
        """現在の実際の外観モードがdarkかどうかを返す（systemを解決）"""
        mode = ctk.get_appearance_mode().lower()
        if mode == "system":
            try:
                import darkdetect
                return bool(darkdetect.isDark())
            except ImportError:  # pragma: no cover
                return False
        return mode == "dark"

    def _apply_tree_style(self) -> None:
        """外観モードに合わせてファイル一覧(Treeview)の色を設定"""
        is_dark = self._resolve_mode()
        style = ttk.Style()
        if is_dark:
            style.theme_use("clam")
            style.configure("Treeview",
                background="#2b2b2b",
                foreground="#dce4ee",
                fieldbackground="#2b2b2b",
                borderwidth=0,
            )
            style.configure("Treeview.Heading",
                background="#333333",
                foreground="#dce4ee",
                relief="flat",
            )
            style.map("Treeview",
                background=[("selected", "#1f538d")],
                foreground=[("selected", "#ffffff")],
            )
            style.map("Treeview.Heading",
                background=[("active", "#404040")],
            )
        else:
            style.theme_use("clam")
            style.configure("Treeview",
                background="#ffffff",
                foreground="#000000",
                fieldbackground="#ffffff",
                borderwidth=0,
            )
            style.configure("Treeview.Heading",
                background="#f0f0f0",
                foreground="#000000",
                relief="flat",
            )
            style.map("Treeview",
                background=[("selected", "#e5f3ff")],
                foreground=[("selected", "#000000")],
            )
            style.map("Treeview.Heading",
                background=[("active", "#e0e0e0")],
            )

    def _start_theme_poll(self) -> None:
        """systemモード時にOSテーマ変更を検出してスタイルを更新"""
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
        """設定ダイアログを開く"""
        SettingsDialog(
            parent=self,
            settings=self._settings,
            on_theme_changed=self._on_theme_changed,
        )

    def _on_recent_selected(self, name: str) -> None:
        if name == "最近のファイル":
            return
        path = Path(name)
        if path.exists():
            self._load_archive(path)

    def _refresh_recent_menu(self) -> None:
        files = self._settings.get("recent_files", [])
        if files:
            display_files = [_truncate_path(f) for f in files]
            self._recent_menu.configure(values=display_files)
            self._recent_var.set(display_files[0] if len(display_files) == 1 else "最近のファイル")

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
        """ドラッグ&ドロップでファイルを受け取る（複数ファイル対応）
        
        アーカイブは読み込み、それ以外は圧縮候補として追加
        """
        raw = getattr(event, "data", "")
        if not raw:
            return
        paths = [p.strip("{}") for p in re.findall(r'\{[^}]+\}|\S+', raw)]
        loaded = False
        compress_candidates: list[Path] = []
        for p in paths:
            path = Path(p)
            if not path.exists():
                continue
            if is_supported(path) and self._zip_path is None:
                if loaded:
                    self._add_to_queue(path)
                else:
                    self._load_archive(path)
                    loaded = True
            elif not is_supported(path):
                # 非アーカイブ → 圧縮候補
                compress_candidates.append(path)
        if compress_candidates and self._zip_path is None:
            self._compress_sources = compress_candidates
            self._status_var.set(f"{len(compress_candidates)}個のファイルを圧縮できます")
            self._start_compress_flow()
        if loaded:
            self._update_queue_status()

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

    def _add_to_queue(self, path: Path) -> None:
        self._archive_paths.append(path)

    def _update_queue_status(self) -> None:
        q = len(self._archive_paths)
        if q > 0:
            current = self._status_var.get()
            self._status_var.set(f"[{q}ファイル] {current}")

    def _load_archive(self, path: Path) -> None:
        try:
            self._entries, self._is_encrypted = list_archive(path)
        except Exception as e:
            self._status_var.set(f"エラー: ファイルを開けません ({e})")
            self._entries = []
            self._refresh_tree()
            self._show_drop_zone()
            self._extract_btn.configure(state="disabled")
            return

        # 新しいアーカイブを開くとき、前の一時展開をクリーンアップ
        if self._temp_dir is not None:
            self._temp_dir.cleanup()
            self._temp_dir = None

        self._zip_path = path
        self._archive_paths = [path]
        self._search_var.set("")

        # RAR/7zはプレビュー用に全展開しておく
        if path.suffix.lower() in {".rar", ".7z"}:
            self._temp_dir = tempfile.TemporaryDirectory()
            try:
                import patoolib
                patoolib.extract_archive(str(path), outdir=self._temp_dir.name)
            except Exception:
                pass
        self._path_var.set(str(path))
        self._settings.add_recent_file(str(path))
        self._refresh_recent_menu()

        # 展開先のデフォルト: アーカイブと同じディレクトリ/ファイル名
        self._dest_var.set(str(path.parent / path.stem))

        total_size = sum(e.size for e in self._entries)
        self._refresh_tree()
        self._show_file_list()
        self._extract_btn.configure(state="normal")
        self._status_var.set(
            f"{len(self._entries)} 個のエントリ ({_format_size(total_size)})"
            + (" (パスワード保護)" if self._is_encrypted else "")
        )

    def _refresh_tree(self) -> None:
        for row in self._tree.get_children():
            self._tree.delete(row)
        query = self._search_var.get().strip().lower()
        filtered = [
            e for e in self._entries
            if not query or query in e.name.lower()
        ] if query else self._entries
        rows = [
            (i, e.name, _format_size(e.size), _format_size(e.compressed_size),
             e.modified.strftime("%Y-%m-%d %H:%M"))
            for i, e in enumerate(filtered, start=1)
        ]
        for values in rows:
            self._tree.insert("", "end", values=values)

    def _on_tree_select(self, _event: object = None) -> None:
        if self._zip_path is None:
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
        """検索ボックスに入力があるたびにツリービューを絞り込む"""
        self._refresh_tree()

    def _show_preview(self, name: str) -> None:
        self._preview_frame.grid_forget()
        self._preview_label.configure(text="")

        ext = Path(name).suffix.lower()
        if ext in _TEXT_EXTENSIONS:
            self._preview_text(name)
        elif ext in _IMAGE_EXTENSIONS:
            self._preview_image(name)
        else:
            self._preview_label.configure(text=f"プレビュー不可 ({ext})")
            self._preview_frame.grid(row=2, column=0, padx=8, pady=(0, 4), sticky="ew")

    def _preview_text(self, name: str) -> None:
        assert self._zip_path is not None
        cache = self._temp_dir.name if self._temp_dir else None
        try:
            content = _read_archive_entry(self._zip_path, name, cache_dir=cache)
        except Exception:
            self._preview_label.configure(text="プレビューを読み込めませんでした")
            self._preview_frame.grid(row=2, column=0, padx=8, pady=(0, 4), sticky="ew")
            return
        text = content.decode("utf-8", errors="replace")[:_MAX_PREVIEW_CHARS]
        self._preview_label.configure(text=text)
        self._preview_frame.grid(row=2, column=0, padx=8, pady=(0, 4), sticky="ew")

    def _preview_image(self, name: str) -> None:
        assert self._zip_path is not None
        cache = self._temp_dir.name if self._temp_dir else None
        try:
            data = _read_archive_entry(self._zip_path, name, cache_dir=cache)
            img = Image.open(io.BytesIO(data))
            # メモリ安全のためサムネイルサイズに制限
            img.thumbnail(_MAX_IMAGE_DIMENSION)
            ctk_img = ctk.CTkImage(img, size=img.size)
            self._preview_label.configure(image=ctk_img, text="")
            # 参照を保持 (GC防止)
            self._current_image = ctk_img
        except Exception:
            self._preview_label.configure(text="画像をプレビューできません")
            self._preview_frame.grid(row=2, column=0, padx=8, pady=(0, 4), sticky="ew")
            return
        self._preview_frame.grid(row=2, column=0, padx=8, pady=(0, 4), sticky="ew")

    def _show_drop_zone(self) -> None:
        self._list_frame.grid_forget()
        self._drop_frame.grid(row=1, column=0, padx=12, pady=4, sticky="nsew")

    def _show_file_list(self) -> None:
        self._drop_frame.grid_forget()
        self._list_frame.grid(row=1, column=0, padx=12, pady=4, sticky="nsew")

    def _on_dest_browse(self) -> None:
        path = filedialog.askdirectory(title="展開先フォルダを選択")
        if path:
            self._dest_var.set(path)
            self._settings.set("last_dest", path)

    def _on_extract(self) -> None:
        if self._extracting or not self._archive_paths:
            return

        dest = Path(self._dest_var.get()) if self._dest_var.get() else Path.cwd()

        # メインスレッドでパスワード取得（アクティブアーカイブのみ）
        active_password: str | None = None
        if self._is_encrypted and self._zip_path is not None:
            active_password = self._settings.get_password(str(self._zip_path))
            if active_password is None:
                active_password = self._ask_password()
                if active_password is None:
                    return
                self._settings.set_password(str(self._zip_path), active_password)

        self._extracting = True
        self._set_ui_enabled(False)
        self._progress.set(0)

        Thread(
            target=self._do_batch_extract,
            args=(list(self._archive_paths), dest, active_password),
            daemon=True,
        ).start()

    def _do_batch_extract(
        self, paths: list[Path], dest: Path, active_password: str | None
    ) -> None:
        self.after(0, self._progress.grid)
        self.after(0, lambda: self._progress.set(0))
        total_archives = len(paths)

        for idx, archive_path in enumerate(paths):
            password = active_password if archive_path == self._zip_path else None
            entry_archive_name = archive_path.name
            archive_dest = dest / archive_path.stem
            archive_dest.mkdir(parents=True, exist_ok=True)

            try:
                _last_progress = [0.0]
                def on_progress(
                    current: int, total: int,
                    current_name: str = "", _a=entry_archive_name,
                ) -> None:
                    now = time.monotonic()
                    if now - _last_progress[0] < 0.1 and current < total:  # pragma: no cover
                        return
                    _last_progress[0] = now
                    pct = current / total
                    self.after(0, lambda p=pct: self._progress.set(p))
                    name_part = f" - {current_name}" if current_name else ""
                    self.after(0, lambda: self._status_var.set(
                        f"[{idx+1}/{total_archives}] {_a}: {pct:.0%} ({current}/{total}){name_part}"
                    ))

                extract_archive(archive_path, archive_dest, password=password, on_progress=on_progress)
            except Exception as exc:
                self.after(0, lambda e=exc, a=entry_archive_name: self._on_extract_error(f"{a}: {e}"))
                return

        self.after(0, self._on_extract_done)

    def _on_extract_done(self) -> None:
        self._extracting = False
        self._set_ui_enabled(True)
        n = len(self._archive_paths)
        self._status_var.set(f"解凍完了 ({n}ファイル)")
        self._archive_paths = []
        self._settings.set("last_dest", self._dest_var.get())
        self._progress.set(1)
        self._progress.grid_remove()
        if self._open_on_done_var.get() and self._zip_path is not None:
            dest = Path(self._dest_var.get()) if self._dest_var.get() else self._zip_path.parent
            subprocess.Popen(["explorer", str(dest)])

    def _on_extract_error(self, msg: str) -> None:
        self._extracting = False
        self._set_ui_enabled(True)
        self._status_var.set(f"エラー: {msg}")
        self._progress.set(0)
        self._progress.grid_remove()

    def _set_ui_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self._browse_btn.configure(state=state)
        self._dest_btn.configure(state=state)
        self._extract_btn.configure(state=state)
        self._compress_btn.configure(state=state)

    def _ask_password(self) -> str | None:
        """パスワード入力ダイアログを表示"""
        dialog = ctk.CTkInputDialog(
            title="パスワード",
            text="このアーカイブはパスワードで保護されています\nパスワードを入力してください:",
        )
        result = dialog.get_input()
        return result if result else None

    # ---- 圧縮機能 ----

    def _on_compress(self) -> None:
        """ファイル/フォルダを圧縮"""
        paths = filedialog.askopenfilenames(title="圧縮するファイルを選択")
        if not paths:
            return
        self._compress_sources = [Path(p) for p in paths]
        self._start_compress_flow()

    def _start_compress_flow(self) -> None:
        """圧縮ファイル保存ダイアログ＋実行"""
        if not self._compress_sources:
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
                ("RAR", "*.rar"),
                ("7z", "*.7z"),
            ],
        )
        if not output:
            return

        self._compressing = True
        self._set_ui_enabled(False)
        self._progress.set(0)
        self._progress.grid()

        Thread(
            target=self._do_compress,
            args=(list(self._compress_sources), Path(output)),
            daemon=True,
        ).start()

    def _do_compress(self, sources: list[Path], output: Path) -> None:
        try:
            def on_progress(cur: int, total_: int, name: str = "") -> None:
                pct = cur / total_
                self.after(0, lambda p=pct: self._progress.set(p))
                self.after(0, lambda: self._status_var.set(
                    f"圧縮中: {pct:.0%} ({cur}/{total_}) - {name}"
                ))

            create_archive(sources, output, on_progress=on_progress)
            self.after(0, self._on_compress_done)
        except Exception as exc:
            msg = str(exc)
            self.after(0, lambda: self._on_compress_error(msg))

    def _on_compress_done(self) -> None:
        self._compressing = False
        self._set_ui_enabled(True)
        self._status_var.set("圧縮完了")
        self._progress.set(1)
        self._progress.grid_remove()
        self._compress_sources = []

    def _on_compress_error(self, msg: str) -> None:
        self._compressing = False
        self._set_ui_enabled(True)
        self._status_var.set(f"エラー: {msg}")
        self._progress.set(0)
        self._progress.grid_remove()


def _read_archive_entry(archive_path: Path | str, name: str, cache_dir: str | None = None) -> bytes:
    """アーカイブ内の1エントリを読み込む。

    ZIPはzipfileで直接読み込み。
    RAR/7zはcache_dir（事前展開済みディレクトリ）があればそこから読み込み、なければ一時展開。
    """
    p = Path(archive_path)
    ext = p.suffix.lower()
    if ext == ".zip":
        import zipfile
        with zipfile.ZipFile(p, "r") as zf:
            return zf.read(name)
    elif ext in {".rar", ".7z"}:
        tmpdir: tempfile.TemporaryDirectory | None = None
        try:
            if cache_dir is not None:
                root = cache_dir
            else:
                tmpdir = tempfile.TemporaryDirectory()
                import patoolib
                try:
                    patoolib.extract_archive(str(p), outdir=tmpdir.name)
                except Exception:
                    return b""
                root = tmpdir.name
            extracted = Path(root) / name
            if extracted.exists():
                return extracted.read_bytes()
            for f in Path(root).rglob("*"):
                if f.is_file() and f.name == Path(name).name:
                    return f.read_bytes()
        finally:
            if tmpdir is not None:
                tmpdir.cleanup()
    return b""


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
    return Path(sys.executable)


def install_context_menu() -> None:
    """Windowsコンテキストメニューにkaitoを登録"""
    exe = _get_exe_path()
    exe_str = f'"{exe}"'
    base = r"Software\Classes"

    # 解凍: 各拡張子
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


def _delete_key_recursive(root_key: object, sub_key: str) -> None:  # type: ignore[type-arg]
    """レジストリキーをサブキーごと削除する"""
    try:
        with OpenKey(root_key, sub_key, 0, KEY_SET_VALUE) as key:  # type: ignore[arg-type]
            info = QueryInfoKey(key)
            for _ in range(info[0]):
                child = EnumKey(key, 0)
                _delete_key_recursive(key, child)
        DeleteKey(root_key, sub_key)  # type: ignore[arg-type]
    except FileNotFoundError:
        pass
    except OSError:
        pass


def uninstall_context_menu() -> None:
    """Windowsコンテキストメニューからkaitoを削除"""
    base = r"Software\Classes"

    for ext in _CONTEXT_EXTENSIONS:
        _delete_key_recursive(HKEY_CURRENT_USER, f"{base}\\SystemFileAssociations\\{ext}\\shell\\kaito_extract")

    for shell_root in [f"{base}\\*", f"{base}\\Directory"]:
        _delete_key_recursive(HKEY_CURRENT_USER, f"{shell_root}\\shell\\kaito_compress")

    print("コンテキストメニューを削除しました")


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1024 ** 2:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 ** 3:
        return f"{size / 1024 ** 2:.1f} MB"
    else:
        return f"{size / 1024 ** 3:.1f} GB"


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

    cli_path: Path | None = None
    cli_compress_path: Path | None = None

    if args and args[0] == "--compress" and len(args) > 1:
        p = Path(args[1])
        if p.exists():
            cli_compress_path = p
    elif args:
        p = Path(args[0])
        if p.suffix.lower() in {".zip", ".rar", ".7z"} and p.exists():
            cli_path = p

    app = UnzipApp(cli_path=cli_path, cli_compress_path=cli_compress_path)
    app.mainloop()  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    main()
