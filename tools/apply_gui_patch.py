from __future__ import annotations

import re
from pathlib import Path

path = Path("src/kaito/gui/unzip_app.py")
text = path.read_text(encoding="utf-8")


def replace_literal(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one literal match, got {count}: {old[:80]!r}")
    text = text.replace(old, new, 1)


def replace_block(pattern: str, replacement: str) -> None:
    global text
    text, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"expected one block match, got {count}: {pattern[:80]!r}")


replace_literal("from threading import Thread", "from threading import Event, Thread")
replace_literal(
    "    InvalidPasswordError,\n    UnsafeArchiveError,",
    "    InvalidPasswordError,\n    PasswordRequiredError,\n    UnsafeArchiveError,",
)
replace_literal(
    "        self._is_busy = False\n\n        self._temp_dir:",
    "        self._is_busy = False\n"
    "        self._closing = False\n"
    "        self._worker_thread: Optional[Thread] = None\n\n"
    "        self._temp_dir:",
)

load_archive = '''    def _load_archive(self, path: Path) -> None:
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
'''
replace_block(
    r"    def _load_archive\(self, path: Path\) -> None:.*?    def _refresh_tree\(self\) -> None:",
    load_archive + "\n    def _refresh_tree(self) -> None:",
)

password_helper = '''    def _request_password_from_worker(
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

'''
replace_literal("    # ---- 展開処理 ----\n", password_helper + "    # ---- 展開処理 ----\n")

extract_methods = '''    def _on_extract(self) -> None:
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
                self.after(0, lambda count=success_count: self._on_extract_cancelled(count))
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
                            lambda count=success_count: self._on_extract_cancelled(count),
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
                        self.after(0, lambda value=percentage: self._progress.set(value))
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
                            lambda name=archive_name, message=str(exc): self._show_error(
                                "安全のため展開を中止しました", f"{name}: {message}"
                            ),
                        )
                        break
                    except UnsafeArchiveError as exc:
                        fail_count += 1
                        self.after(
                            0,
                            lambda name=archive_name, message=str(exc): self._show_error(
                                "安全でないエントリを検出しました", f"{name}: {message}"
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
                            lambda count=success_count: self._on_extract_cancelled(count),
                        )
                        return
                    except ArchiveError as exc:
                        fail_count += 1
                        self.after(
                            0,
                            lambda name=archive_name, message=exc.user_message(): (
                                self._show_error("展開に失敗しました", f"{name}: {message}")
                            ),
                        )
                        break
            except CancelledError:
                self.after(0, lambda count=success_count: self._on_extract_cancelled(count))
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

'''
replace_block(
    r"    def _on_extract\(self\) -> None:.*?    def _on_extract_done\(self, success: int, fail: int\) -> None:",
    extract_methods + "    def _on_extract_done(self, success: int, fail: int) -> None:",
)

replace_literal(
    "    def _on_extract_done(self, success: int, fail: int) -> None:\n"
    "        self._is_busy = False",
    "    def _on_extract_done(self, success: int, fail: int) -> None:\n"
    "        self._worker_thread = None\n"
    "        self._is_busy = False",
)
replace_literal(
    "    def _on_extract_cancelled(self, success: int) -> None:\n"
    "        self._is_busy = False",
    "    def _on_extract_cancelled(self, success: int) -> None:\n"
    "        self._worker_thread = None\n"
    "        self._is_busy = False",
)

close_method = '''    def _on_close(self) -> None:
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

'''
replace_block(
    r"    def _on_close\(self\) -> None:.*?    # ---- 圧縮機能 ----",
    close_method + "    # ---- 圧縮機能 ----",
)

replace_literal(
    "        if self._compress_no_dialog:\n"
    "            self._compress_no_dialog = False\n"
    "            first = self._compress_sources[0]",
    "        if self._compress_no_dialog:\n"
    "            first = self._compress_sources[0]",
)
replace_literal(
    "        Thread(\n"
    "            target=self._do_compress,\n"
    "            args=(list(self._compress_sources), output),\n"
    "            daemon=False,\n"
    "        ).start()",
    "        self._worker_thread = Thread(\n"
    "            target=self._do_compress,\n"
    "            args=(list(self._compress_sources), output),\n"
    "            daemon=False,\n"
    "        )\n"
    "        self._worker_thread.start()",
)
text = text.replace("self._archive_service._cancel_event.is_set()", "self._archive_service.is_cancelled()")

replace_literal(
    "    def _on_compress_done(self) -> None:\n"
    "        self._is_busy = False",
    "    def _on_compress_done(self) -> None:\n"
    "        self._worker_thread = None\n"
    "        self._is_busy = False",
)
replace_literal(
    "        self._compress_sources = []\n"
    "        if self._compress_no_dialog:\n"
    "            self.after(500, self.destroy)\n"
    "        else:\n"
    "            self._set_ui_enabled(True)",
    "        self._compress_sources = []\n"
    "        close_after = self._compress_no_dialog\n"
    "        self._compress_no_dialog = False\n"
    "        if close_after:\n"
    "            self.after(500, self.destroy)\n"
    "        else:\n"
    "            self._set_ui_enabled(True)",
)
replace_literal(
    "    def _on_compress_cancelled(self) -> None:\n"
    "        self._is_busy = False",
    "    def _on_compress_cancelled(self) -> None:\n"
    "        self._worker_thread = None\n"
    "        self._is_busy = False",
)
replace_literal(
    "        self._compress_sources = []\n"
    "        self._set_ui_enabled(True)\n\n"
    "    def _on_compress_error",
    "        self._compress_sources = []\n"
    "        self._compress_no_dialog = False\n"
    "        self._set_ui_enabled(True)\n\n"
    "    def _on_compress_error",
)
replace_literal(
    "    def _on_compress_error(self, msg: str) -> None:\n"
    "        self._is_busy = False",
    "    def _on_compress_error(self, msg: str) -> None:\n"
    "        self._worker_thread = None\n"
    "        self._is_busy = False",
)

path.write_text(text, encoding="utf-8")
