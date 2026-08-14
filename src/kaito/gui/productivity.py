"""Optional productivity features layered onto the main kaito window."""

from __future__ import annotations

import io
import warnings
from pathlib import Path
from threading import Thread
from tkinter import messagebox
from typing import TYPE_CHECKING, Callable

import customtkinter as ctk
from PIL import Image

from kaito.archive.inspection import (
    ArchiveSafetyReport,
    expand_selected_members,
    filter_entries,
)
from kaito.archive.service import ArchiveService
from kaito.diagnostics import build_diagnostic_report
from kaito.domain.errors import ArchiveError, CancelledError
from kaito.domain.models import ArchiveInfo, ExtractionOptions

if TYPE_CHECKING:
    from kaito.gui.unzip_app import UnzipApp

_FILTER_VALUES = [
    "すべて",
    "画像",
    "文書",
    "アーカイブ",
    "実行ファイル",
    "大きいファイル",
    "暗号化",
]
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


class _ArchivePasswordDialog(ctk.CTkToplevel):  # pragma: no cover - GUI
    """Modal single-password dialog whose value is always masked."""

    def __init__(self, parent: ctk.CTk, archive_name: str, *, retry: bool) -> None:
        super().__init__(parent)
        self._result: str | None = None
        self.title("パスワードが正しくありません" if retry else "パスワード")
        self.geometry("440x225")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.grid_columnconfigure(0, weight=1)

        heading = "パスワードを再入力" if retry else "暗号化アーカイブ"
        prompt = (
            f"「{archive_name}」のパスワードが正しくありません。"
            if retry
            else f"「{archive_name}」はパスワードで保護されています。"
        )
        ctk.CTkLabel(
            self,
            text=heading,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, padx=24, pady=(22, 4), sticky="w")
        ctk.CTkLabel(
            self,
            text=prompt,
            text_color=("#667085", "#a9b4c2"),
            anchor="w",
        ).grid(row=1, column=0, padx=24, pady=(0, 12), sticky="w")

        self._password = ctk.CTkEntry(
            self,
            show="*",
            placeholder_text="パスワード",
        )
        self._password.grid(row=2, column=0, padx=24, pady=4, sticky="ew")

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=3, column=0, padx=24, pady=(16, 20), sticky="e")
        ctk.CTkButton(buttons, text="キャンセル", command=self._cancel).pack(
            side="left", padx=(0, 6)
        )
        ctk.CTkButton(buttons, text="決定", command=self._accept).pack(side="left")
        self._password.focus_set()
        self.bind("<Return>", lambda _event: self._accept())
        self.bind("<Escape>", lambda _event: self._cancel())

    def _accept(self) -> None:
        password = self._password.get()
        if not password:
            messagebox.showerror(
                "パスワード", "パスワードを入力してください", parent=self
            )
            return
        self._result = password
        self._password.delete(0, "end")
        self.destroy()

    def _cancel(self) -> None:
        self._result = None
        self._password.delete(0, "end")
        self.destroy()

    def get_password(self) -> str | None:
        self.wait_window()
        return self._result


class _CreationPasswordDialog(ctk.CTkToplevel):  # pragma: no cover - GUI
    """Modal password + confirmation dialog with masked fields."""

    def __init__(self, parent: ctk.CTk, format_name: str) -> None:
        super().__init__(parent)
        self._result: str | None = None
        self.title(f"{format_name.upper()}を暗号化")
        self.geometry("430x260")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self,
            text="暗号化パスワード",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, padx=24, pady=(22, 4), sticky="w")
        ctk.CTkLabel(
            self,
            text="パスワードは保存されず、ログや診断にも出力されません。",
            text_color=("#667085", "#a9b4c2"),
        ).grid(row=1, column=0, padx=24, pady=(0, 12), sticky="w")

        self._password = ctk.CTkEntry(self, show="*", placeholder_text="パスワード")
        self._password.grid(row=2, column=0, padx=24, pady=4, sticky="ew")
        self._confirm = ctk.CTkEntry(
            self, show="*", placeholder_text="パスワードを再入力"
        )
        self._confirm.grid(row=3, column=0, padx=24, pady=4, sticky="ew")

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=4, column=0, padx=24, pady=(16, 20), sticky="e")
        ctk.CTkButton(buttons, text="キャンセル", command=self._cancel).pack(
            side="left", padx=(0, 6)
        )
        ctk.CTkButton(buttons, text="暗号化", command=self._accept).pack(side="left")
        self._password.focus_set()
        self.bind("<Return>", lambda _event: self._accept())
        self.bind("<Escape>", lambda _event: self._cancel())

    def _clear_entries(self) -> None:
        self._password.delete(0, "end")
        self._confirm.delete(0, "end")

    def _accept(self) -> None:
        password = self._password.get()
        if not password:
            messagebox.showerror(
                "パスワード", "パスワードを入力してください", parent=self
            )
            return
        if password != self._confirm.get():
            messagebox.showerror(
                "パスワード", "確認用パスワードが一致しません", parent=self
            )
            return
        if len(password) < 8:
            if not messagebox.askyesno(
                "短いパスワード",
                "8文字未満のパスワードは推奨されません。続行しますか？",
                parent=self,
            ):
                return
        self._result = password
        self._clear_entries()
        self.destroy()

    def _cancel(self) -> None:
        self._result = None
        self._clear_entries()
        self.destroy()

    def get_password(self) -> str | None:
        self.wait_window()
        return self._result


class ProductivityFeatures:
    """Attach inspection, selective extraction, filtering, and support tools."""

    def __init__(self, app: UnzipApp) -> None:  # pragma: no cover - GUI wiring
        self.app = app
        self._safety_report: ArchiveSafetyReport | None = None
        self._last_error: str | None = None

        self._original_refresh_tree: Callable[[], None] = app._refresh_tree
        self._original_load_archive: Callable[[Path], None] = app._load_archive
        self._original_start_compress: Callable[[Path], None] = app._start_compress
        self._original_set_ui_enabled: Callable[[bool], None] = app._set_ui_enabled
        self._original_recent_selected: Callable[[str], None] = app._on_recent_selected

        self._filter_var = ctk.StringVar(value="すべて")
        app._list_frame.grid_columnconfigure(2, weight=0)
        self._filter_menu = ctk.CTkOptionMenu(
            app._list_frame,
            values=_FILTER_VALUES,
            variable=self._filter_var,
            width=120,
            height=24,
            command=lambda _value: self.refresh_tree(),
        )
        self._filter_menu.grid(row=0, column=2, padx=(0, 8), pady=(6, 0))

        toolbar = ctk.CTkFrame(app._list_frame, fg_color="transparent")
        toolbar.grid(row=3, column=0, columnspan=3, padx=8, pady=(0, 8), sticky="ew")
        toolbar.grid_columnconfigure(0, weight=1)

        self._safety_label = ctk.CTkLabel(toolbar, text="安全診断: 未実施", anchor="w")
        self._safety_label.grid(row=0, column=0, padx=(0, 6), sticky="w")
        self._safety_button = ctk.CTkButton(
            toolbar, text="安全診断", width=82, command=self.show_safety_report
        )
        self._safety_button.grid(row=0, column=1, padx=3)
        self._integrity_button = ctk.CTkButton(
            toolbar, text="整合性検査", width=92, command=self.test_integrity
        )
        self._integrity_button.grid(row=0, column=2, padx=3)
        self._selected_button = ctk.CTkButton(
            toolbar, text="選択を解凍", width=92, command=self.extract_selected
        )
        self._selected_button.grid(row=0, column=3, padx=3)
        self._diagnostics_button = ctk.CTkButton(
            toolbar, text="診断コピー", width=92, command=self.copy_diagnostics
        )
        self._diagnostics_button.grid(row=0, column=4, padx=3)
        app._tree.configure(selectmode="extended")
        app._tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        app._recent_menu.configure(command=self.on_recent_selected)
        setattr(app, "_refresh_tree", self.refresh_tree)
        setattr(app, "_load_archive", self.load_archive)
        setattr(app, "_start_compress", self.start_compress)
        setattr(app, "_set_ui_enabled", self.set_ui_enabled)
        setattr(app, "_ask_password", self.ask_password)
        setattr(app, "_show_password_error", self.show_password_error)

    def ask_password(self, archive_name: str) -> str | None:
        return _ArchivePasswordDialog(
            self.app, archive_name, retry=False
        ).get_password()

    def show_password_error(self, archive_name: str) -> str | None:
        return _ArchivePasswordDialog(self.app, archive_name, retry=True).get_password()

    def on_recent_selected(self, display_name: str) -> None:
        if display_name == "履歴を削除":
            self.app._settings.set("recent_files", [])
            self.app._recent_display_to_path.clear()
            self.app._refresh_recent_menu()
            self.app._status_var.set("最近のファイル履歴を削除しました")
            return
        self._original_recent_selected(display_name)

    def refresh_tree(self) -> None:
        for row in self.app._tree.get_children():
            self.app._tree.delete(row)
        entries = filter_entries(
            self.app._entries,
            self.app._search_var.get(),
            self._filter_var.get(),
        )
        for index, entry in enumerate(entries, start=1):
            self.app._tree.insert(
                "",
                "end",
                values=(
                    index,
                    entry.name,
                    _format_size(entry.size),
                    _format_size(entry.compressed_size),
                    entry.modified.strftime("%Y-%m-%d %H:%M"),
                ),
            )

    def _apply_safety_controls(self, enabled: bool = True) -> None:
        has_archive = self.app._current_archive_path is not None and bool(
            self.app._entries
        )
        blocked = (
            self._safety_report is not None and not self._safety_report.can_extract
        )
        extraction_state = (
            "normal" if enabled and has_archive and not blocked else "disabled"
        )
        self.app._extract_btn.configure(state=extraction_state)
        self._selected_button.configure(state=extraction_state)

    def load_archive(self, path: Path) -> None:
        self._original_load_archive(path)
        if self.app._current_archive_path != path or not self.app._entries:
            self._safety_report = None
            self._safety_label.configure(text="安全診断: 未実施")
            self._apply_safety_controls(enabled=not self.app._is_busy)
            return
        info = ArchiveInfo(
            path=path,
            entries=list(self.app._entries),
            is_encrypted=self.app._is_encrypted,
            format_name=path.suffix.lower().lstrip("."),
        )
        self._safety_report = self.app._archive_service.analyze_archive(info)
        report = self._safety_report
        label = f"安全診断: {report.summary}"
        if report.status == "blocked":
            self._safety_label.configure(text=label, text_color="#dc2626")
        elif report.status == "warning":
            self._safety_label.configure(text=label, text_color="#d97706")
        else:
            self._safety_label.configure(text=label, text_color=("#15803d", "#4ade80"))
        self._apply_safety_controls(enabled=not self.app._is_busy)

    def show_safety_report(self) -> None:
        if self._safety_report is None:
            messagebox.showinfo(
                "安全診断", "アーカイブを開いてください", parent=self.app
            )
            return
        messagebox.showinfo(
            "アーカイブ安全診断",
            self._safety_report.format_text(),
            parent=self.app,
        )

    def on_tree_select(self, _event: object = None) -> None:
        path = self.app._current_archive_path
        if path is None:
            return
        selected = self.app._tree.selection()
        if not selected:
            return
        values = self.app._tree.item(selected[0], "values")
        if not values or len(values) < 2:
            return
        entry_name = str(values[1])
        entry = next(
            (item for item in self.app._entries if item.name == entry_name), None
        )
        if entry is None:
            return

        self.app._prev_preview_token += 1
        token = self.app._prev_preview_token
        self.app._preview_frame.grid_forget()
        self.app._preview_label.configure(text="プレビューを読み込み中...", image=None)
        self.app._current_image = None
        self.app._preview_frame.grid(row=2, column=0, padx=8, pady=(0, 4), sticky="ew")

        max_size = int(self.app._archive_service.safety_limits.preview_max_size)
        if entry.size > max_size:
            self.app._preview_label.configure(
                text=f"ファイルが大きすぎてプレビューできません ({_format_size(entry.size)})"
            )
            return

        password = self.app._get_password_for(path)

        def worker() -> None:
            result = self._load_preview(path, entry_name, password)
            self.app.after(0, lambda: self._finish_preview(token, path, result))

        Thread(target=worker, daemon=True).start()

    def _load_preview(
        self, path: Path, entry_name: str, password: str | None
    ) -> tuple[str, object]:
        extension = Path(entry_name).suffix.lower()
        if extension not in _TEXT_EXTENSIONS | _IMAGE_EXTENSIONS:
            return "message", "プレビュー不可"
        try:
            data = self.app._archive_service.read_entry(
                path,
                entry_name,
                password=password,
            )
        except Exception:
            return "message", "プレビューを読み込めませんでした"
        if data is None:
            return "message", "プレビューを読み込めませんでした"
        if extension in _TEXT_EXTENSIONS:
            return "text", _decode_text(data)

        pixel_limit = int(
            self.app._archive_service.safety_limits.preview_max_image_pixels
        )
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as opened:
                    pixels = opened.width * opened.height
                    if pixels > pixel_limit:
                        return (
                            "message",
                            f"画像の画素数が上限を超えています ({pixels:,} > {pixel_limit:,})",
                        )
                    opened.load()
                    opened.thumbnail((400, 250))
                    image = opened.copy()
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            return "message", "画像が大きすぎてプレビューできません"
        except Exception:
            return "message", "画像をプレビューできません"
        return "image", image

    def _finish_preview(
        self,
        token: int,
        path: Path,
        result: tuple[str, object],
    ) -> None:
        if (
            token != self.app._prev_preview_token
            or self.app._current_archive_path != path
            or self.app._closing
        ):
            return
        kind, value = result
        if kind == "image" and isinstance(value, Image.Image):
            ctk_image = ctk.CTkImage(value, size=value.size)
            self.app._preview_label.configure(image=ctk_image, text="")
            self.app._current_image = ctk_image
        else:
            self.app._preview_label.configure(image=None, text=str(value))
            self.app._current_image = None
        self.app._preview_frame.grid(row=2, column=0, padx=8, pady=(0, 4), sticky="ew")

    def _password_for_current_archive(self) -> str | None:
        path = self.app._current_archive_path
        if path is None:
            return None
        password = self.app._get_password_for(path)
        if self.app._is_encrypted and password is None:
            password = self.app._ask_password(path.name)
            if password:
                self.app._set_password_for(path, password)
        return password

    def _begin_indeterminate(self, status: str) -> bool:
        if self.app._is_busy:
            return False
        self.app._is_busy = True
        self.app._archive_service.reset_cancel()
        self.set_ui_enabled(False)
        self.app._show_cancel_button(True)
        self.app._status_var.set(status)
        self.app._progress.configure(mode="indeterminate")
        self.app._progress.grid()
        self.app._progress.start()
        return True

    def _end_indeterminate(self) -> None:
        self.app._progress.stop()
        self.app._progress.configure(mode="determinate")
        self.app._progress.grid_remove()
        self.app._show_cancel_button(False)
        self.app._is_busy = False
        self.app._worker_thread = None
        self.set_ui_enabled(True)

    def test_integrity(self) -> None:
        path = self.app._current_archive_path
        if path is None:
            messagebox.showinfo(
                "整合性検査", "アーカイブを開いてください", parent=self.app
            )
            return
        password = self._password_for_current_archive()
        if self.app._is_encrypted and password is None:
            return
        if not self._begin_indeterminate(f"{path.name} の整合性を検査中..."):
            return

        def worker() -> None:
            try:
                result = self.app._archive_service.test_archive(path, password=password)
            except CancelledError:
                self.app.after(
                    0, lambda: self._finish_integrity(None, "検査をキャンセルしました")
                )
            except ArchiveError as exc:
                self.app.after(
                    0,
                    lambda message=exc.user_message(): self._finish_integrity(
                        None, message
                    ),
                )
            except Exception as exc:
                self.app.after(
                    0, lambda message=str(exc): self._finish_integrity(None, message)
                )
            else:
                self.app.after(0, lambda: self._finish_integrity(result, None))

        self.app._worker_thread = Thread(target=worker, daemon=False)
        self.app._worker_thread.start()

    def _finish_integrity(self, result: object | None, error: str | None) -> None:
        self._end_indeterminate()
        if error is not None:
            self._last_error = error
            self.app._status_var.set(f"整合性検査: {error}")
            messagebox.showerror("整合性検査", error, parent=self.app)
            return
        if result is None:
            return
        passed = bool(getattr(result, "passed", False))
        message = str(getattr(result, "message", ""))
        checked = int(getattr(result, "checked_entries", 0))
        self.app._status_var.set(f"整合性検査完了: {checked}件")
        if passed:
            messagebox.showinfo("整合性検査", message, parent=self.app)
        else:
            self._last_error = message
            messagebox.showerror("整合性検査", message, parent=self.app)

    def extract_selected(self) -> None:
        path = self.app._current_archive_path
        if path is None:
            return
        if self._safety_report is not None and not self._safety_report.can_extract:
            messagebox.showerror(
                "選択を解凍",
                "安全診断で拒否されたアーカイブは選択項目も解凍できません。",
                parent=self.app,
            )
            return
        selected_names: list[str] = []
        for item_id in self.app._tree.selection():
            values = self.app._tree.item(item_id, "values")
            if values and len(values) >= 2:
                selected_names.append(str(values[1]))
        members = expand_selected_members(self.app._entries, selected_names)
        if not members:
            messagebox.showinfo(
                "選択を解凍",
                "一覧からファイルまたはフォルダーを選択してください",
                parent=self.app,
            )
            return

        password = self._password_for_current_archive()
        if self.app._is_encrypted and password is None:
            return
        base_text = self.app._dest_var.get().strip()
        base = Path(base_text) if base_text else path.parent
        selected_member_names = set(members)
        selected_entries = [
            entry for entry in self.app._entries if entry.name in selected_member_names
        ]
        destination = ArchiveService.resolve_extract_dest(
            base,
            path,
            selected_entries,
            avoid_existing=True,
        )
        if not self._begin_indeterminate(f"選択した{len(members)}項目を解凍中..."):
            return

        def on_progress(current: int, total: int, name: str = "") -> None:
            if self.app._archive_service.is_cancelled():
                raise CancelledError(str(path))
            self.app.after(
                0,
                lambda: self.app._status_var.set(
                    f"選択を解凍中: {current}/{max(total, 1)} {name}"
                ),
            )

        def worker() -> None:
            try:
                self.app._archive_service.extract(
                    path,
                    ExtractionOptions(
                        dest_dir=destination,
                        password=password,
                        members=members,
                        on_progress=on_progress,
                    ),
                )
            except CancelledError:
                self.app.after(
                    0, lambda: self._finish_selected(None, "解凍をキャンセルしました")
                )
            except ArchiveError as exc:
                self.app.after(
                    0,
                    lambda message=exc.user_message(): self._finish_selected(
                        None, message
                    ),
                )
            except Exception as exc:
                self.app.after(
                    0, lambda message=str(exc): self._finish_selected(None, message)
                )
            else:
                self.app.after(0, lambda: self._finish_selected(destination, None))

        self.app._worker_thread = Thread(target=worker, daemon=False)
        self.app._worker_thread.start()

    def _finish_selected(self, destination: Path | None, error: str | None) -> None:
        self._end_indeterminate()
        if error is not None:
            self._last_error = error
            self.app._status_var.set(error)
            if "キャンセル" not in error:
                messagebox.showerror("選択を解凍", error, parent=self.app)
            return
        if destination is None:
            return
        self.app._status_var.set(f"選択項目を解凍しました: {destination}")
        if self.app._open_on_done_var.get():
            self.app._open_folder(destination)

    def copy_diagnostics(self) -> None:
        report = build_diagnostic_report(
            self.app._archive_service,
            archive_path=self.app._current_archive_path,
            entry_count=len(self.app._entries)
            if self.app._current_archive_path
            else None,
            encrypted=self.app._is_encrypted
            if self.app._current_archive_path
            else None,
            last_error=self._last_error,
        )
        self.app.clipboard_clear()
        self.app.clipboard_append(report)
        self.app.update_idletasks()
        messagebox.showinfo(
            "診断レポート",
            "個人パスとパスワードを除外した診断レポートをクリップボードへコピーしました。",
            parent=self.app,
        )

    def start_compress(self, output: Path) -> None:
        setattr(self.app, "_compress_password", None)
        if not self.app._compress_no_dialog and output.suffix.lower() in {
            ".zip",
            ".7z",
        }:
            choice = messagebox.askyesnocancel(
                "暗号化",
                "パスワードで暗号化しますか？\n\n"
                "ZIPはAES-256、7zはAES-256とヘッダー暗号化を使用します。",
                parent=self.app,
            )
            if choice is None:
                return
            if choice:
                password = _CreationPasswordDialog(
                    self.app, output.suffix.lower().lstrip(".")
                ).get_password()
                if password is None:
                    return
                setattr(self.app, "_compress_password", password)
        self._original_start_compress(output)
        if not self.app._is_busy:
            setattr(self.app, "_compress_password", None)

    def set_ui_enabled(self, enabled: bool) -> None:
        self._original_set_ui_enabled(enabled)
        state = "normal" if enabled else "disabled"
        self._filter_menu.configure(state=state)
        self._safety_button.configure(state=state)
        self._integrity_button.configure(state=state)
        self._diagnostics_button.configure(state=state)
        self._apply_safety_controls(enabled=enabled)


def _decode_text(data: bytes, max_chars: int = _MAX_PREVIEW_CHARS) -> str:
    try:
        return data.decode("utf-8")[:max_chars]
    except UnicodeDecodeError:
        pass
    try:
        import locale

        return data.decode(locale.getencoding())[:max_chars]
    except (UnicodeDecodeError, LookupError):
        return data.decode("utf-8", errors="replace")[:max_chars]


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024**2:
        return f"{size / 1024:.1f} KB"
    if size < 1024**3:
        return f"{size / 1024**2:.1f} MB"
    return f"{size / 1024**3:.1f} GB"
