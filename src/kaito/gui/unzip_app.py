"""
src/kaito/gui/unzip_app.py
CustomTkinterを使用したZIP解凍GUIアプリ
ドラッグ&ドロップ対応 (tkinterdnd2)
関連: unzip.py (解凍コアロジック)
"""

import sys
from pathlib import Path
from threading import Thread
from tkinter import filedialog, ttk

import customtkinter as ctk
from tkinterdnd2 import TkinterDnD

from kaito.unzip import ZipEntry, extract_all, list_entries


class UnzipApp(ctk.CTk, TkinterDnD.DnDWrapper):
    """ZIP解凍GUIメインウィンドウ"""

    def __init__(self, cli_path: Path | None = None) -> None:
        super().__init__()

        self.TkdndVersion = TkinterDnD._require(self)

        self.title("解凍ソフト")
        self.geometry("720x520")
        self.minsize(600, 400)

        self._zip_path: Path | None = None
        self._entries: list[ZipEntry] = []
        self._is_encrypted = False
        self._extracting = False

        self._build_ui()

        # ウィンドウ全体をドロップターゲットに設定
        self.drop_target_register("*")
        self.dnd_bind("<<Drop>>", self._on_drop)

        # 起動時にファイルが渡されたら読み込む
        if cli_path is not None:
            self._load_zip(cli_path)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

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
        list_frame = ctk.CTkFrame(self)
        list_frame.grid(row=1, column=0, padx=12, pady=4, sticky="nsew")
        list_frame.grid_rowconfigure(1, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(list_frame, text="内容:").grid(
            row=0, column=0, padx=8, pady=(8, 2), sticky="w"
        )

        # ttk.Treeview を CTkFrame に埋め込む
        tree_frame = ctk.CTkFrame(list_frame)
        tree_frame.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="nsew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        columns = ("name", "size", "compressed", "date")
        self._tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", height=12
        )
        self._tree.heading("name", text="名前")
        self._tree.heading("size", text="サイズ")
        self._tree.heading("compressed", text="圧縮後")
        self._tree.heading("date", text="更新日時")
        self._tree.column("name", width=280, minwidth=160, stretch=True)
        self._tree.column("size", width=90, minwidth=70, stretch=False)
        self._tree.column("compressed", width=90, minwidth=70, stretch=False)
        self._tree.column("date", width=140, minwidth=100, stretch=False)

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

        self._status_var = ctk.StringVar(value="ZIPファイルを選択してください")
        self._status_label = ctk.CTkLabel(
            bottom_frame, textvariable=self._status_var, anchor="w"
        )
        self._status_label.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="w")

        self._extract_btn = ctk.CTkButton(
            bottom_frame, text="解凍実行", command=self._on_extract
        )
        self._extract_btn.grid(row=1, column=2, padx=(4, 8), pady=(0, 8), sticky="e")

    # ---- イベントハンドラ ----

    def _on_drop(self, event: object) -> None:
        """ドラッグ&ドロップでファイルを受け取る"""
        raw = getattr(event, "data", "")
        if not raw:
            return
        # パスを抽出: {} で囲まれている場合と複数ファイルに対応
        path_str = raw.strip("{}").split()[0] if " " in raw else raw.strip("{}")
        path = Path(path_str)
        if path.suffix.lower() == ".zip" and path.exists():
            self._load_zip(path)

    def _on_browse(self) -> None:
        path = filedialog.askopenfilename(
            title="ZIPファイルを選択",
            filetypes=[("ZIPファイル", "*.zip"), ("すべてのファイル", "*.*")],
        )
        if not path:
            return
        self._load_zip(Path(path))

    def _load_zip(self, path: Path) -> None:
        try:
            self._entries, self._is_encrypted = list_entries(path)
        except Exception as e:
            self._status_var.set(f"エラー: ZIPファイルを開けません ({e})")
            return

        self._zip_path = path
        self._path_var.set(str(path))

        # 展開先のデフォルト: ZIPファイルと同じディレクトリ/ZIPファイル名
        default_dest = path.parent / path.stem
        if not self._dest_var.get():
            self._dest_var.set(str(default_dest))

        self._refresh_tree()
        self._status_var.set(
            f"{len(self._entries)} 個のエントリ"
            + (" (パスワード保護)" if self._is_encrypted else "")
        )

    def _refresh_tree(self) -> None:
        for row in self._tree.get_children():
            self._tree.delete(row)
        for e in self._entries:
            self._tree.insert("", "end", values=(
                e.name,
                _format_size(e.size),
                _format_size(e.compressed_size),
                e.modified.strftime("%Y-%m-%d %H:%M"),
            ))

    def _on_dest_browse(self) -> None:
        path = filedialog.askdirectory(title="展開先フォルダを選択")
        if path:
            self._dest_var.set(path)

    def _on_extract(self) -> None:
        if self._extracting or self._zip_path is None:
            return

        dest = Path(self._dest_var.get()) if self._dest_var.get() else Path.cwd()
        dest.mkdir(parents=True, exist_ok=True)

        password: str | None = None
        if self._is_encrypted:
            password = self._ask_password()
            if password is None:
                return

        self._extracting = True
        self._set_ui_enabled(False)
        self._progress.set(0)

        Thread(
            target=self._do_extract,
            args=(self._zip_path, dest, password),
            daemon=True,
        ).start()

    def _do_extract(
        self, zip_path: Path, dest: Path, password: str | None
    ) -> None:
        def on_progress(current: int, total: int) -> None:
            self.after(0, lambda: self._progress.set(current / total))
            self.after(0, lambda: self._status_var.set(
                f"解凍中... {current}/{total}"
            ))

        try:
            extract_all(zip_path, dest, password=password, on_progress=on_progress)
            self.after(0, self._on_extract_done)
        except Exception as exc:
            self.after(0, lambda e=exc: self._on_extract_error(str(e)))

    def _on_extract_done(self) -> None:
        self._extracting = False
        self._set_ui_enabled(True)
        self._status_var.set("解凍完了")
        self._progress.set(1)

    def _on_extract_error(self, msg: str) -> None:
        self._extracting = False
        self._set_ui_enabled(True)
        self._status_var.set(f"エラー: {msg}")
        self._progress.set(0)

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
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    cli_path: Path | None = None
    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
        if p.suffix.lower() == ".zip" and p.exists():
            cli_path = p
    app = UnzipApp(cli_path=cli_path)
    app.mainloop()


if __name__ == "__main__":
    main()
