"""
src/kaito/gui/unzip_app.py
CustomTkinterを使用したZIP解凍GUIアプリ
ドラッグ&ドロップ対応 (tkinterdnd2)
関連: unzip.py (解凍コアロジック)
"""

__version__ = "0.5.0"

import re
import sys
from pathlib import Path
from threading import Thread
from tkinter import filedialog, ttk

import customtkinter as ctk
from tkinterdnd2 import TkinterDnD

from kaito.settings import SettingsManager
from kaito.unzip import (
    ZipEntry,
    extract_archive,
    is_supported,
    list_archive,
)

_DROP_BORDER_COLOR = "#3a7ebf"
_DROP_HIGHLIGHT_COLOR = "#1a6ebf"


class UnzipApp(ctk.CTk, TkinterDnD.DnDWrapper):
    """ZIP解凍GUIメインウィンドウ"""

    def __init__(self, cli_path: Path | None = None) -> None:
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

        self._build_ui()

        self._settings = SettingsManager()

        # 保存済み設定を復元
        saved_dest = self._settings.get("last_dest")
        if saved_dest:
            self._dest_var.set(saved_dest)
        self._open_on_done_var.set(self._settings.get("open_on_done", True))

        # ウィンドウ全体をドロップターゲットに設定
        self.drop_target_register("*")
        self.dnd_bind("<<Drop>>", self._on_drop)
        self.dnd_bind("<<DragEnter>>", self._on_drag_enter)
        self.dnd_bind("<<DragLeave>>", self._on_drag_leave)

        # 起動時にファイルが渡されたら読み込む
        if cli_path is not None:
            self._load_archive(cli_path)

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

        # --- ファイル一覧 ---
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
        self._list_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self._list_frame, text="内容:").grid(
            row=0, column=0, padx=8, pady=(8, 2), sticky="w"
        )

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
        bottom_frame.grid_columnconfigure(1, weight=1)

        self._progress = ctk.CTkProgressBar(bottom_frame, mode="determinate")
        self._progress.grid(row=0, column=0, columnspan=3, padx=8, pady=(8, 4), sticky="ew")
        self._progress.set(0)
        self._progress.grid_remove()  # 解凍中のみ表示

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
        self._status_label.grid(row=2, column=0, padx=8, pady=(0, 8), sticky="w")

        self._extract_btn = ctk.CTkButton(
            bottom_frame, text="解凍実行", command=self._on_extract, state="disabled"
        )
        self._extract_btn.grid(row=2, column=2, padx=(4, 8), pady=(0, 8), sticky="e")

    # ---- イベントハンドラ ----

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
        """ドラッグ&ドロップでファイルを受け取る（複数ファイル対応）"""
        raw = getattr(event, "data", "")
        if not raw:
            return
        paths = [p.strip("{}") for p in re.findall(r'\{[^}]+\}|\S+', raw)]
        loaded = False
        for p in paths:
            path = Path(p)
            if is_supported(path) and path.exists():
                if loaded:
                    self._add_to_queue(path)
                else:
                    self._load_archive(path)
                    loaded = True
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

        self._zip_path = path
        self._archive_paths = [path]
        self._path_var.set(str(path))
        self._settings.add_recent_file(str(path))

        # 展開先のデフォルト: ZIPファイルと同じディレクトリ/ZIPファイル名
        default_dest = path.parent / path.stem
        if not self._dest_var.get():
            self._dest_var.set(str(default_dest))

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
        for i, e in enumerate(self._entries, start=1):
            self._tree.insert("", "end", values=(
                i,
                e.name,
                _format_size(e.size),
                _format_size(e.compressed_size),
                e.modified.strftime("%Y-%m-%d %H:%M"),
            ))

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
                def on_progress(
                    current: int, total: int,
                    current_name: str = "", _a=entry_archive_name,
                ) -> None:
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
            import subprocess
            subprocess.Popen(["explorer", str(dest)], shell=True)

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

    def _ask_password(self) -> str | None:
        """パスワード入力ダイアログを表示"""
        dialog = ctk.CTkInputDialog(
            title="パスワード",
            text="このZIPファイルはパスワードで保護されています\nパスワードを入力してください:",
        )
        result = dialog.get_input()
        return result if result else None


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
    settings = SettingsManager()
    ctk.set_appearance_mode(settings.get("theme", "system"))
    ctk.set_default_color_theme("blue")
    cli_path: Path | None = None
    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
        if p.suffix.lower() == ".zip" and p.exists():
            cli_path = p
    app = UnzipApp(cli_path=cli_path)
    app.mainloop()  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    main()
