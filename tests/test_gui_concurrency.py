"""GUIのパスワード同期、展開先、終了処理の回帰テスト。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from kaito.domain.errors import PasswordRequiredError
from kaito.domain.models import ArchiveEntry, ArchiveInfo
from kaito.gui.unzip_app import UnzipApp


def _bare_app() -> UnzipApp:
    app = UnzipApp.__new__(UnzipApp)
    app.__dict__.update(
        {
            "_archive_queue": [],
            "_entries": [],
            "_is_encrypted": False,
            "_is_busy": False,
            "_closing": False,
            "_worker_thread": None,
            "_compress_sources": [],
            "_compress_no_dialog": False,
            "_passwords": {},
            "_failed_passwords": set(),
            "_current_archive_path": None,
            "_temp_dir": None,
            "_archive_service": MagicMock(),
            "_dest_var": MagicMock(),
            "_status_var": MagicMock(),
            "_progress": MagicMock(),
            "_settings": MagicMock(),
            "_path_var": MagicMock(),
            "_search_var": MagicMock(),
            "_extract_btn": MagicMock(),
            "_compress_btn": MagicMock(),
            "_open_on_done_var": MagicMock(),
            "_close_on_done_var": MagicMock(),
        }
    )
    app.after = MagicMock(side_effect=lambda _delay, callback: callback())
    app.destroy = MagicMock()
    app._show_cancel_button = MagicMock()
    app._set_ui_enabled = MagicMock()
    app._cleanup_temp_dir = MagicMock()
    app._refresh_recent_menu = MagicMock()
    app._refresh_tree = MagicMock()
    app._show_drop_zone = MagicMock()
    app._show_file_list = MagicMock()
    app._update_queue_status = MagicMock()
    app._show_error = MagicMock()
    app._archive_service.is_cancelled.return_value = False
    return app


def test_password_dialog_cancel_completes_worker_wait() -> None:
    app = _bare_app()
    app._ask_password = MagicMock(return_value=None)

    assert app._request_password_from_worker("secret.rar") is None
    app._ask_password.assert_called_once_with("secret.rar")


def test_password_retry_uses_error_dialog() -> None:
    app = _bare_app()
    app._show_password_error = MagicMock(return_value="correct")

    assert app._request_password_from_worker("secret.rar", retry=True) == "correct"
    app._show_password_error.assert_called_once_with("secret.rar")


def test_header_encrypted_archive_prompts_and_retries(tmp_path: Path) -> None:
    app = _bare_app()
    archive = tmp_path / "header-encrypted.7z"
    archive.touch()
    info = ArchiveInfo(
        path=archive,
        entries=[
            ArchiveEntry(
                name="secret.txt",
                size=1,
                compressed_size=1,
                modified=datetime(2026, 1, 1),
                is_dir=False,
                is_encrypted=True,
            )
        ],
        is_encrypted=True,
        format_name="7z",
    )
    app._archive_service.list_archive.side_effect = [
        PasswordRequiredError(str(archive)),
        info,
    ]
    app._ask_password = MagicMock(return_value="correct")

    app._load_archive(archive)

    assert app._get_password_for(archive) == "correct"
    assert app._archive_service.list_archive.call_count == 2
    assert app._archive_service.list_archive.call_args_list[1].kwargs["password"] == (
        "correct"
    )
    assert app._current_archive_path == archive


def test_default_destination_is_base_directory_not_double_nested(
    tmp_path: Path,
) -> None:
    app = _bare_app()
    archive = tmp_path / "sample.zip"
    app._current_archive_path = archive

    app._update_dest_display()

    app._dest_var.set.assert_called_once_with(str(tmp_path))


def test_context_compression_keeps_auto_close_flag_until_completion(
    tmp_path: Path,
) -> None:
    app = _bare_app()
    source = tmp_path / "input.txt"
    source.write_text("data", encoding="utf-8")
    app._compress_sources = [source]
    app._compress_no_dialog = True
    app._start_compress = MagicMock()

    app._start_compress_flow()

    assert app._compress_no_dialog is True
    app._start_compress.assert_called_once_with(tmp_path / "input.zip")


def test_compress_done_resets_flag_and_schedules_close() -> None:
    app = _bare_app()
    app._is_busy = True
    app._compress_no_dialog = True

    app._on_compress_done()

    assert app._compress_no_dialog is False
    assert app._worker_thread is None
    app.after.assert_called_with(500, app.destroy)


def test_close_during_work_cancels_and_waits_for_worker() -> None:
    app = _bare_app()
    app._is_busy = True
    worker = MagicMock()
    worker.is_alive.return_value = True
    app._worker_thread = worker

    with patch("kaito.gui.unzip_app.messagebox.askyesno", return_value=True):
        app._on_close()

    assert app._closing is True
    app._archive_service.cancel.assert_called_once_with()
    app.after.assert_called_with(100, app._wait_for_worker_then_destroy)
    app.destroy.assert_not_called()


def test_worker_shutdown_destroys_only_after_exit() -> None:
    app = _bare_app()
    worker = MagicMock()
    worker.is_alive.return_value = False
    app._worker_thread = worker

    app._wait_for_worker_then_destroy()

    app._cleanup_temp_dir.assert_called_once_with()
    app.destroy.assert_called_once_with()
