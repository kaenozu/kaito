"""GUIのパスワード同期、展開先、終了処理の回帰テスト。

origin/master 版は「オープン時パスワード再試行・ワーカー終了待ち」を
UnzipApp の自前ワーカースレッド（_worker_thread / _wait_for_worker_then_destroy）で
実装していた。統合後（feature 版 UI + ArchiveService バックエンド）は
ExtractWorker 経由のため、ここでは feature 版の API に合わせて
「ヘッダー暗号化のオープン時パスワード再試行」と「圧縮フローのフラグ保持」を固定する。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from kaito.domain.errors import PasswordRequiredError
from kaito.domain.models import ArchiveEntry
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
            "_compress_sources": [],
            "_compress_no_dialog": False,
            "_zip_path": None,
            "_temp_dir": None,
            "_archive_service": MagicMock(),
            "_dest_var": MagicMock(),
            "_status_var": MagicMock(),
            "_status_label": MagicMock(),
            "_progress": MagicMock(),
            "_settings": MagicMock(),
            "_settings.get_password.return_value": None,
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


def test_header_encrypted_archive_prompts_and_retries(tmp_path: Path) -> None:
    """ヘッダー暗号化7zはオープン時にパスワードを要求し、再試行で開ける"""
    app = _bare_app()
    archive = tmp_path / "header-encrypted.7z"
    archive.touch()
    entries = [
        ArchiveEntry(
            name="secret.txt",
            size=1,
            compressed_size=1,
            modified=datetime(2026, 1, 1),
            is_dir=False,
            is_encrypted=True,
        )
    ]
    with (
        patch(
            "kaito.gui.unzip_app.list_archive",
            side_effect=[PasswordRequiredError(str(archive)), (entries, True)],
        ),
        patch.object(app, "_ask_password_for", return_value="correct") as mock_ask,
    ):
        app._load_archive(archive)

    assert app._zip_path == archive
    assert app._entries == entries
    assert app._is_encrypted is True
    mock_ask.assert_called_once_with(archive)
    app._settings.set_password.assert_called_once_with(str(archive), "correct")


def test_header_encrypted_cancel_aborts_load(tmp_path: Path) -> None:
    """パスワード入力をキャンセルすると読み込みを中断する"""
    app = _bare_app()
    archive = tmp_path / "header-encrypted.7z"
    archive.touch()
    with (
        patch(
            "kaito.gui.unzip_app.list_archive",
            side_effect=PasswordRequiredError(str(archive)),
        ),
        patch.object(app, "_ask_password_for", return_value=None),
    ):
        app._load_archive(archive)

    assert app._zip_path is None
    app._status_var.set.assert_called()
    app._settings.set_password.assert_not_called()


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
