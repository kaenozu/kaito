"""
tests/test_unzip_app.py
unzip_app.py のテスト（GUIコンポーネントは全てmock）
"""

from contextlib import ExitStack
from datetime import datetime
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kaito.gui.unzip_app import (
    _format_size,
    _resolve_extract_dest,
    _truncate_path,
    _read_archive_entry,
    main as app_main,
)


# ---- _format_size のテスト ----


class TestFormatSize:
    def test_bytes(self) -> None:
        assert _format_size(0) == "0 B"
        assert _format_size(512) == "512 B"
        assert _format_size(1023) == "1023 B"

    def test_kilobytes(self) -> None:
        assert _format_size(1024) == "1.0 KB"
        assert _format_size(1536) == "1.5 KB"
        assert _format_size(1024 * 1024 - 1) == "1024.0 KB"

    def test_megabytes(self) -> None:
        assert _format_size(1024 * 1024) == "1.0 MB"
        assert _format_size(5 * 1024 * 1024) == "5.0 MB"
        assert _format_size(1024 * 1024 * 1024 - 1) == "1024.0 MB"

    def test_gigabytes(self) -> None:
        assert _format_size(1024**3) == "1.0 GB"
        assert _format_size(3 * 1024**3) == "3.0 GB"


# ---- main() のテスト ----


class TestMain:
    def test_main_no_args(self) -> None:
        with (
            patch("sys.argv", ["kaito"]),
            patch("kaito.gui.unzip_app.ctk.set_appearance_mode") as mode,
            patch("kaito.gui.unzip_app.ctk.set_default_color_theme") as theme,
            patch("kaito.gui.unzip_app.UnzipApp") as app,
            patch("kaito.gui.unzip_app.SettingsManager.get", return_value="system"),
        ):
            app_main()
            mode.assert_called_once_with("system")
            theme.assert_called_once_with("blue")
            app.assert_called_once_with(cli_path=None, cli_compress_path=None)

    def test_main_with_zip(self, tmp_path: Path) -> None:
        z = tmp_path / "test.zip"
        z.write_text("dummy")
        with (
            patch("sys.argv", ["kaito", str(z)]),
            patch("kaito.gui.unzip_app.ctk.set_appearance_mode"),
            patch("kaito.gui.unzip_app.ctk.set_default_color_theme"),
            patch("kaito.gui.unzip_app.UnzipApp") as app,
        ):
            app_main()
            assert app.call_args.kwargs["cli_path"].name == "test.zip"

    def test_main_non_zip_arg(self) -> None:
        with (
            patch("sys.argv", ["kaito", "readme.txt"]),
            patch("kaito.gui.unzip_app.ctk.set_appearance_mode"),
            patch("kaito.gui.unzip_app.ctk.set_default_color_theme"),
            patch("kaito.gui.unzip_app.UnzipApp") as app,
        ):
            app_main()
            app.assert_called_once_with(cli_path=None, cli_compress_path=None)

    def test_main_nonexistent_arg(self) -> None:
        with (
            patch("sys.argv", ["kaito", "no.zip"]),
            patch("kaito.gui.unzip_app.ctk.set_appearance_mode"),
            patch("kaito.gui.unzip_app.ctk.set_default_color_theme"),
            patch("kaito.gui.unzip_app.UnzipApp") as app,
        ):
            app_main()
            app.assert_called_once_with(cli_path=None, cli_compress_path=None)

    def test_main_with_rar(self, tmp_path: Path) -> None:
        r = tmp_path / "test.rar"
        r.write_text("dummy")
        with (
            patch("sys.argv", ["kaito", str(r)]),
            patch("kaito.gui.unzip_app.ctk.set_appearance_mode"),
            patch("kaito.gui.unzip_app.ctk.set_default_color_theme"),
            patch("kaito.gui.unzip_app.UnzipApp") as app,
            patch("kaito.gui.unzip_app.SettingsManager.get", return_value="system"),
        ):
            app_main()
            assert app.call_args.kwargs["cli_path"].name == "test.rar"

    def test_main_with_7z(self, tmp_path: Path) -> None:
        s = tmp_path / "test.7z"
        s.write_text("dummy")
        with (
            patch("sys.argv", ["kaito", str(s)]),
            patch("kaito.gui.unzip_app.ctk.set_appearance_mode"),
            patch("kaito.gui.unzip_app.ctk.set_default_color_theme"),
            patch("kaito.gui.unzip_app.UnzipApp") as app,
            patch("kaito.gui.unzip_app.SettingsManager.get", return_value="system"),
        ):
            app_main()
            assert app.call_args.kwargs["cli_path"].name == "test.7z"


# ---- UnzipApp のメソッドテスト (モックインスタンス) ----


def _make_app_mock() -> MagicMock:
    """__init__ を呼ばずにモックしたUnzipAppインスタンスを作成"""
    from kaito.gui.unzip_app import UnzipApp

    app = UnzipApp.__new__(UnzipApp)
    app.__dict__["_current_archive_path"] = None
    app.__dict__["_archive_queue"] = []
    app.__dict__["_entries"] = []
    app.__dict__["_is_encrypted"] = False
    app.__dict__["_is_busy"] = False
    app.__dict__["_cancel_flag"] = MagicMock()
    app.__dict__["_compress_sources"] = []
    app.__dict__["_compressing"] = False
    app.__dict__["_compress_no_dialog"] = False
    app.__dict__["_passwords"] = {}
    app.__dict__["_failed_passwords"] = set()
    app.__dict__["_temp_dir"] = None
    app.__dict__["_tree_poll_id"] = None
    app.__dict__["_tree_last_dark"] = None
    app.__dict__["_recent_display_to_path"] = {}
    app.__dict__["_prev_preview_token"] = 0
    app.__dict__["_current_image"] = None

    # Mock UI widgets
    app.__dict__["_path_var"] = MagicMock()
    app.__dict__["_dest_var"] = MagicMock()
    app.__dict__["_status_var"] = MagicMock()
    app.__dict__["_progress"] = MagicMock()
    app.__dict__["_tree"] = MagicMock()
    app.__dict__["_browse_btn"] = MagicMock()
    app.__dict__["_dest_btn"] = MagicMock()
    app.__dict__["_extract_btn"] = MagicMock()
    app.__dict__["_compress_btn"] = MagicMock()
    app.__dict__["_cancel_btn"] = MagicMock()
    app.__dict__["_drop_frame"] = MagicMock()
    app.__dict__["_list_frame"] = MagicMock()
    app.__dict__["_drop_label"] = MagicMock()
    app.__dict__["_queue_label"] = MagicMock()
    app.__dict__["_preview_frame"] = MagicMock()
    app.__dict__["_preview_label"] = MagicMock()
    app.__dict__["_search_var"] = MagicMock()
    app.__dict__["_search_entry"] = MagicMock()
    app.__dict__["_open_on_done_var"] = MagicMock()
    app.__dict__["_close_on_done_var"] = MagicMock()
    app.__dict__["_recent_var"] = MagicMock()
    app.__dict__["_recent_menu"] = MagicMock()
    app.__dict__["_settings_btn"] = MagicMock()
    app.__dict__["_settings"] = MagicMock()
    app.__dict__["_archive_service"] = MagicMock()
    app.__dict__["_tree_poll_id"] = None

    app.after = MagicMock()
    app.destroy = MagicMock()
    return app


class TestUnzipAppMethods:
    """UnzipApp の個別メソッド（モックインスタンスでテスト）"""

    @pytest.fixture
    def app(self) -> MagicMock:
        return _make_app_mock()

    def test_drag_enter_highlights(self, app: MagicMock) -> None:
        app._on_drag_enter()
        app._drop_frame.configure.assert_called_with(border_color="#1a6ebf")

    def test_drag_leave_restores(self, app: MagicMock) -> None:
        app._on_drag_leave()
        app._drop_frame.configure.assert_called_with(border_color="#3a7ebf")

    def test_highlight_drop_drop_frame_missing(self, app: MagicMock) -> None:
        app._drop_frame.configure.side_effect = AttributeError
        app._highlight_drop(True)

    def test_on_browse_no_file(self, app: MagicMock) -> None:
        with (
            patch("tkinter.filedialog.askopenfilename", return_value=""),
            patch.object(app, "_load_archive") as mock_load,
        ):
            app._on_browse()
            mock_load.assert_not_called()

    def test_on_browse_with_file(self, app: MagicMock, tmp_path: Path) -> None:
        z = tmp_path / "test.zip"
        z.touch()
        with (
            patch("tkinter.filedialog.askopenfilename", return_value=str(z)),
            patch.object(app, "_load_archive") as mock_load,
        ):
            app._on_browse()
            mock_load.assert_called_once()

    def test_on_dest_browse_with_path(self, app: MagicMock) -> None:
        with patch("tkinter.filedialog.askdirectory", return_value="C:\\out"):
            app._on_dest_browse()
            app._dest_var.set.assert_called_with("C:\\out")

    def test_on_dest_browse_cancel(self, app: MagicMock) -> None:
        with patch("tkinter.filedialog.askdirectory", return_value=""):
            app._on_dest_browse()
            app._dest_var.set.assert_not_called()

    def test_on_extract_no_queue(self, app: MagicMock) -> None:
        app.__dict__["_is_busy"] = False
        app.__dict__["_archive_queue"] = []
        app._on_extract()
        assert not app.__dict__["_is_busy"]

    def test_on_extract_already_busy(self, app: MagicMock) -> None:
        app.__dict__["_is_busy"] = True
        app.__dict__["_archive_queue"] = [Path("x.zip")]
        app._on_extract()
        assert app.__dict__["_is_busy"]

    def test_set_ui_enabled_disabled(self, app: MagicMock) -> None:
        app._set_ui_enabled(False)
        app._browse_btn.configure.assert_called_with(state="disabled")
        app._dest_btn.configure.assert_called_with(state="disabled")
        app._extract_btn.configure.assert_called_with(state="disabled")

    def test_set_ui_enabled_enabled(self, app: MagicMock) -> None:
        app._set_ui_enabled(True)
        app._browse_btn.configure.assert_called_with(state="normal")
        app._dest_btn.configure.assert_called_with(state="normal")
        app._extract_btn.configure.assert_called_with(state="normal")

    def test_ask_password_typed(self, app: MagicMock) -> None:
        with patch("kaito.gui.unzip_app.ctk.CTkInputDialog") as dlg:
            dlg.return_value.get_input.return_value = "secret"
            result = app._ask_password("test.rar")
            assert result == "secret"
            text_arg = dlg.call_args[1]["text"]
            assert "アーカイブ" in text_arg or "パスワード" in text_arg

    def test_ask_password_cancelled(self, app: MagicMock) -> None:
        with patch("kaito.gui.unzip_app.ctk.CTkInputDialog") as dlg:
            dlg.return_value.get_input.return_value = None
            result = app._ask_password("test.rar")
            assert result is None

    def test_show_cancel_button(self, app: MagicMock) -> None:
        app._show_cancel_button(True)
        app._cancel_btn.grid.assert_called_once()
        app._show_cancel_button(False)
        app._cancel_btn.grid_remove.assert_called()

    def test_password_management(self, app: MagicMock) -> None:
        p = Path("test.zip")
        assert app._get_password_for(p) is None
        app._set_password_for(p, "secret")
        assert app._get_password_for(p) == "secret"
        app._mark_password_failed(p)
        assert app._get_password_for(p) is None
        assert str(p) in app._failed_passwords
        app._clear_passwords()
        assert app._failed_passwords == set()

    def test_on_extract_done(self, app: MagicMock) -> None:
        app.__dict__["_is_busy"] = True
        app._on_extract_done(1, 0)
        assert not app.__dict__["_is_busy"]
        app._status_var.set.assert_called_with("解凍完了 (1ファイル)")

    def test_on_extract_cancelled(self, app: MagicMock) -> None:
        app.__dict__["_is_busy"] = True
        app._on_extract_cancelled(0)
        assert not app.__dict__["_is_busy"]
        app._status_var.set.assert_called_with(
            "解凍をキャンセルしました (0ファイル完了)"
        )

    def test_on_compress_done(self, app: MagicMock) -> None:
        app.__dict__["_is_busy"] = True
        app._on_compress_done()
        assert not app.__dict__["_is_busy"]

    def test_on_compress_error(self, app: MagicMock) -> None:
        app.__dict__["_is_busy"] = True
        app._on_compress_error("disk full")
        assert not app.__dict__["_is_busy"]

    def test_on_compress_cancelled(self, app: MagicMock) -> None:
        app.__dict__["_is_busy"] = True
        app._on_compress_cancelled()
        assert not app.__dict__["_is_busy"]
        app._status_var.set.assert_called_with("圧縮をキャンセルしました")

    def test_truncate_path_short(self) -> None:
        assert _truncate_path("C:\\a.zip") == "C:\\a.zip"

    def test_truncate_path_long(self) -> None:
        long_path = "C:\\" + "very_long_directory_name\\" * 10 + "file.zip"
        result = _truncate_path(long_path, max_len=60)
        assert len(result) <= 60
        assert "..." in result or "\\" in result

    def test_format_size_zero(self) -> None:
        assert _format_size(0) == "0 B"

    def test_format_size_kb(self) -> None:
        assert _format_size(1024) == "1.0 KB"

    def test_format_size_mb(self) -> None:
        assert _format_size(1024 * 1024) == "1.0 MB"

    def test_format_size_gb(self) -> None:
        assert _format_size(1024**3) == "1.0 GB"


# ---- _read_archive_entry のテスト ----


class TestReadArchiveEntry:
    def test_zip_entry(self, tmp_path: Path) -> None:
        z = tmp_path / "test.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("hello.txt", "data")
        assert _read_archive_entry(z, "hello.txt") == b"data"

    def test_zip_missing_entry(self, tmp_path: Path) -> None:
        z = tmp_path / "test.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("hello.txt", "data")
        assert _read_archive_entry(z, "missing.txt") == b""


# ---- _resolve_extract_dest のテスト ----


class TestResolveExtractDest:
    def test_single_root_no_double_nesting(self) -> None:
        from kaito.domain.models import ArchiveEntry

        dest = Path("C:\\out")
        archive = Path("C:\\myproject.zip")
        entries = [
            ArchiveEntry(
                name="myproject/file1.js",
                size=0,
                compressed_size=0,
                modified=datetime.now(),
                is_dir=False,
            ),
            ArchiveEntry(
                name="myproject/sub/file2.js",
                size=0,
                compressed_size=0,
                modified=datetime.now(),
                is_dir=False,
            ),
        ]
        result = _resolve_extract_dest(dest, archive, entries)
        assert result == dest

    def test_root_files_creates_subfolder(self) -> None:
        from kaito.domain.models import ArchiveEntry

        dest = Path("C:\\out")
        archive = Path("C:\\archive.zip")
        entries = [
            ArchiveEntry(
                name="readme.txt",
                size=0,
                compressed_size=0,
                modified=datetime.now(),
                is_dir=False,
            ),
            ArchiveEntry(
                name="sub/file.txt",
                size=0,
                compressed_size=0,
                modified=datetime.now(),
                is_dir=False,
            ),
        ]
        result = _resolve_extract_dest(dest, archive, entries)
        assert result == dest / "archive"

    def test_no_entries(self) -> None:
        dest = Path("C:\\out")
        archive = Path("C:\\empty.zip")
        result = _resolve_extract_dest(dest, archive, [])
        assert result == dest / "empty"

    def test_multiple_roots(self) -> None:
        from kaito.domain.models import ArchiveEntry

        dest = Path("C:\\out")
        archive = Path("C:\\multi.zip")
        entries = [
            ArchiveEntry(
                name="dir1/a.txt",
                size=0,
                compressed_size=0,
                modified=datetime.now(),
                is_dir=False,
            ),
            ArchiveEntry(
                name="dir2/b.txt",
                size=0,
                compressed_size=0,
                modified=datetime.now(),
                is_dir=False,
            ),
        ]
        result = _resolve_extract_dest(dest, archive, entries)
        assert result == dest / "multi"


# ---- CLI引数テスト ----


class TestMainCLI:
    def test_install_context_menu_flag(self) -> None:
        with (
            patch("sys.argv", ["kaito", "--install-context-menu"]),
            patch("kaito.gui.unzip_app.install_context_menu") as mock_install,
        ):
            app_main()
            mock_install.assert_called_once()

    def test_uninstall_context_menu_flag(self) -> None:
        with (
            patch("sys.argv", ["kaito", "--uninstall-context-menu"]),
            patch("kaito.gui.unzip_app.uninstall_context_menu") as mock_uninstall,
        ):
            app_main()
            mock_uninstall.assert_called_once()

    def test_compress_flag(self, tmp_path: Path) -> None:
        f = tmp_path / "myfolder"
        f.mkdir()
        with (
            patch("sys.argv", ["kaito", "--compress", str(f)]),
            patch("kaito.gui.unzip_app.ctk.set_appearance_mode"),
            patch("kaito.gui.unzip_app.ctk.set_default_color_theme"),
            patch("kaito.gui.unzip_app.UnzipApp") as app,
        ):
            app_main()
            assert app.call_args.kwargs["cli_compress_path"] == f

    def test_compress_flag_nonexistent(self, tmp_path: Path) -> None:
        with (
            patch("sys.argv", ["kaito", "--compress", "C:\\nope"]),
            patch("kaito.gui.unzip_app.ctk.set_appearance_mode"),
            patch("kaito.gui.unzip_app.ctk.set_default_color_theme"),
            patch("kaito.gui.unzip_app.UnzipApp") as app,
        ):
            app_main()
            assert app.call_args.kwargs["cli_compress_path"] is None
