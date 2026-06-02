"""
tests/test_unzip_app.py
unzip_app.py のテスト（GUIコンポーネントは全てmock）
"""

import sys
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kaito.gui.unzip_app import _format_size, main as app_main


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
        assert _format_size(1024 ** 3) == "1.0 GB"
        assert _format_size(3 * 1024 ** 3) == "3.0 GB"


# ---- main() のテスト ----

class TestMain:
    def test_main_no_args(self) -> None:
        with (
            patch("sys.argv", ["kaito"]),
            patch("kaito.gui.unzip_app.ctk.set_appearance_mode") as mode,
            patch("kaito.gui.unzip_app.ctk.set_default_color_theme") as theme,
            patch("kaito.gui.unzip_app.UnzipApp") as app,
        ):
            app_main()
            mode.assert_called_once_with("system")
            theme.assert_called_once_with("blue")
            app.assert_called_once_with(cli_path=None)

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
            app.assert_called_once_with(cli_path=None)

    def test_main_nonexistent_arg(self) -> None:
        with (
            patch("sys.argv", ["kaito", "no.zip"]),
            patch("kaito.gui.unzip_app.ctk.set_appearance_mode"),
            patch("kaito.gui.unzip_app.ctk.set_default_color_theme"),
            patch("kaito.gui.unzip_app.UnzipApp") as app,
        ):
            app_main()
            app.assert_called_once_with(cli_path=None)


# ---- UnzipApp の全メソッドテスト ----

def _make_app_mock() -> MagicMock:
    """__init__ を呼ばずにモックしたUnzipAppインスタンスを作成"""
    from kaito.gui.unzip_app import UnzipApp

    app = UnzipApp.__new__(UnzipApp)

    # __init__ で設定されるインスタンス変数
    app._zip_path = None
    app._entries = []
    app._is_encrypted = False
    app._extracting = False
    app._path_var = MagicMock()
    app._dest_var = MagicMock()
    app._status_var = MagicMock()
    app._progress = MagicMock()
    app._tree = MagicMock()
    app._browse_btn = MagicMock()
    app._dest_btn = MagicMock()
    app._extract_btn = MagicMock()
    app.after = MagicMock()
    app.drop_target_register = MagicMock()
    app.dnd_bind = MagicMock()
    app.title = MagicMock()
    app.geometry = MagicMock()
    app.minsize = MagicMock()
    app.grid_columnconfigure = MagicMock()
    app.grid_rowconfigure = MagicMock()
    return app


class TestUnzipAppInit:
    """__init__ のテスト（cli_path の有無）"""

    def test_init_no_path(self) -> None:
        from kaito.gui.unzip_app import UnzipApp
        with (
            patch.object(UnzipApp, "_build_ui"),
            patch.object(UnzipApp, "drop_target_register"),
            patch.object(UnzipApp, "dnd_bind"),
            patch.object(UnzipApp, "title"),
            patch.object(UnzipApp, "geometry"),
            patch.object(UnzipApp, "minsize"),
            patch.object(UnzipApp, "grid_columnconfigure"),
            patch.object(UnzipApp, "grid_rowconfigure"),
            patch.object(UnzipApp, "TkdndVersion", create=True),
            patch("kaito.gui.unzip_app.TkinterDnD._require"),
        ):
            app = UnzipApp(cli_path=None)
            assert app._zip_path is None
            assert app._entries == []
            assert not app._is_encrypted
            assert not app._extracting

    def test_init_with_path(self, tmp_path: Path) -> None:
        z = tmp_path / "test.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("a.txt", "data")

        from kaito.gui.unzip_app import UnzipApp
        with (
            patch.object(UnzipApp, "_build_ui"),
            patch.object(UnzipApp, "drop_target_register"),
            patch.object(UnzipApp, "dnd_bind"),
            patch.object(UnzipApp, "title"),
            patch.object(UnzipApp, "geometry"),
            patch.object(UnzipApp, "minsize"),
            patch.object(UnzipApp, "grid_columnconfigure"),
            patch.object(UnzipApp, "grid_rowconfigure"),
            patch.object(UnzipApp, "TkdndVersion", create=True),
            patch("kaito.gui.unzip_app.TkinterDnD._require"),
            patch.object(UnzipApp, "_path_var", create=True),
            patch.object(UnzipApp, "_dest_var", create=True),
            patch.object(UnzipApp, "_status_var", create=True),
            patch.object(UnzipApp, "_tree", create=True),
            patch.object(UnzipApp, "_refresh_tree"),
        ):
            app = UnzipApp(cli_path=z)
            assert app._zip_path == z
            assert len(app._entries) == 1


class TestUnzipAppMethods:
    """UnzipApp の個別メソッド（モックインスタンスでテスト）"""

    @pytest.fixture
    def app(self) -> MagicMock:
        return _make_app_mock()

    def test_on_drop_no_data(self, app: MagicMock) -> None:
        with patch.object(app, "_load_zip") as mock_load:
            event = MagicMock()
            type(event).data = ""
            app._on_drop(event)
            mock_load.assert_not_called()

    def test_on_drop_non_zip(self, app: MagicMock, tmp_path: Path) -> None:
        event = MagicMock()
        type(event).data = str(tmp_path / "readme.txt")
        with patch.object(app, "_load_zip") as mock_load:
            app._on_drop(event)
            mock_load.assert_not_called()

    def test_on_drop_zip(self, app: MagicMock, tmp_path: Path) -> None:
        z = tmp_path / "test.zip"
        z.touch()
        event = MagicMock()
        type(event).data = str(z)
        with (
            patch.object(app, "_load_zip") as mock_load,
            patch.object(Path, "exists", return_value=True),
        ):
            app._on_drop(event)
            mock_load.assert_called_once()

    def test_on_browse_no_file(self, app: MagicMock) -> None:
        with (
            patch("tkinter.filedialog.askopenfilename", return_value=""),
            patch.object(app, "_load_zip") as mock_load,
        ):
            app._on_browse()
            mock_load.assert_not_called()

    def test_on_browse_with_file(self, app: MagicMock, tmp_path: Path) -> None:
        z = tmp_path / "test.zip"
        z.touch()
        with (
            patch("tkinter.filedialog.askopenfilename", return_value=str(z)),
            patch.object(app, "_load_zip") as mock_load,
        ):
            app._on_browse()
            mock_load.assert_called_once()

    def test_load_zip_success(self, app: MagicMock, tmp_path: Path) -> None:
        z = tmp_path / "test.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("hello.txt", "data")
            zf.writestr("sub/file.txt", "data2")
        app._dest_var.get.return_value = ""
        app._load_zip(z)
        assert app._zip_path == z
        assert len(app._entries) == 2
        assert app._path_var.set.called
        assert app._dest_var.set.called

    def test_load_zip_error(self, app: MagicMock, tmp_path: Path) -> None:
        z = tmp_path / "bad.zip"
        z.write_text("not a zip")
        app._load_zip(z)
        app._status_var.set.assert_called()
        assert app._zip_path is None

    def test_load_zip_with_existing_dest(self, app: MagicMock, tmp_path: Path) -> None:
        z = tmp_path / "test.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("a.txt", "data")
        app._dest_var.get.return_value = "C:\\custom\\path"
        app._load_zip(z)
        # dest_var は既に設定済みなので上書きしない
        app._dest_var.set.assert_not_called()

    def test_refresh_tree(self, app: MagicMock) -> None:
        from datetime import datetime
        from kaito.unzip import ZipEntry
        app._entries = [
            ZipEntry("file.txt", 100, 80, datetime(2026, 6, 2, 10, 0, 0), False),
            ZipEntry("dir/", 0, 0, datetime(2026, 1, 1, 0, 0, 0), True),
        ]
        app._tree.get_children.return_value = ["old"]
        app._refresh_tree()
        app._tree.delete.assert_called_with("old")
        assert app._tree.insert.call_count == 2

    def test_on_dest_browse_with_path(self, app: MagicMock) -> None:
        with patch("tkinter.filedialog.askdirectory", return_value="C:\\out"):
            app._on_dest_browse()
            app._dest_var.set.assert_called_with("C:\\out")

    def test_on_dest_browse_cancel(self, app: MagicMock) -> None:
        with patch("tkinter.filedialog.askdirectory", return_value=""):
            app._on_dest_browse()
            app._dest_var.set.assert_not_called()

    def test_on_extract_no_zip(self, app: MagicMock) -> None:
        app._zip_path = None
        app._on_extract()
        # _set_ui_enabled は呼ばれない
        app._browse_btn.configure.assert_not_called()

    def test_on_extract_already_busy(self, app: MagicMock) -> None:
        app._zip_path = Path("x.zip")
        app._extracting = True
        app._on_extract()
        app._browse_btn.configure.assert_not_called()

    def test_on_extract_normal(self, app: MagicMock, tmp_path: Path) -> None:
        z = tmp_path / "test.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("a.txt", "data")
        app._zip_path = z
        app._is_encrypted = False
        app._dest_var.get.return_value = ""
        app._on_extract()
        assert app._extracting

    def test_on_extract_encrypted_manual(self, app: MagicMock, tmp_path: Path) -> None:
        z = tmp_path / "test.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("a.txt", "data")
        app._zip_path = z
        app._is_encrypted = True
        app._dest_var.get.return_value = str(tmp_path / "out")
        with (
            patch("kaito.gui.unzip_app.ctk.CTkInputDialog") as dlg,
            patch.object(app, "_set_ui_enabled"),
        ):
            dlg.return_value.get_input.return_value = "mypass"
            with patch("threading.Thread"):
                app._on_extract()
                assert app._extracting

    def test_on_extract_encrypted_cancel(self, app: MagicMock, tmp_path: Path) -> None:
        z = tmp_path / "test.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("a.txt", "data")
        app._zip_path = z
        app._is_encrypted = True
        with (
            patch("kaito.gui.unzip_app.ctk.CTkInputDialog") as dlg,
        ):
            dlg.return_value.get_input.return_value = None
            app._on_extract()
            assert not app._extracting

    def test_do_extract_success(self, app: MagicMock, tmp_path: Path) -> None:
        z = tmp_path / "test.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("a.txt", "data")
        dest = tmp_path / "out"
        app._do_extract(z, dest, password=None)
        assert (dest / "a.txt").read_text() == "data"
        # after で _on_extract_done がキューされた
        after_calls = app.after.call_args_list
        assert len(after_calls) >= 1

        # キューされたコールバックを実行
        for _, kwargs in after_calls:
            cb = kwargs if callable(kwargs) else None
            if cb is None and len(after_calls[0]) > 1:
                cb = after_calls[0][1]
            if cb:
                cb()

    def test_do_extract_error(self, app: MagicMock, tmp_path: Path) -> None:
        z = tmp_path / "bad.zip"
        z.write_text("not a zip")
        dest = tmp_path / "out"
        app._do_extract(z, dest, password=None)
        # エラーコールバックがキューされたことを確認
        assert app.after.called

    def test_on_extract_done(self, app: MagicMock) -> None:
        app._extracting = True
        app._on_extract_done()
        assert not app._extracting
        app._progress.set.assert_called_with(1)
        app._status_var.set.assert_called_with("解凍完了")

    def test_on_extract_error(self, app: MagicMock) -> None:
        app._extracting = True
        app._on_extract_error("disk full")
        assert not app._extracting
        app._status_var.set.assert_called_with("エラー: disk full")
        app._progress.set.assert_called_with(0)

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
            result = app._ask_password()
            assert result == "secret"

    def test_ask_password_cancelled(self, app: MagicMock) -> None:
        with patch("kaito.gui.unzip_app.ctk.CTkInputDialog") as dlg:
            dlg.return_value.get_input.return_value = None
            result = app._ask_password()
            assert result is None
