"""
tests/test_settings.py
settings.py のテスト
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from kaito.settings import MAX_RECENT_FILES, SettingsManager


class TestSettingsManager:
    def test_defaults_on_missing_file(self, tmp_path: Path) -> None:
        cfg = tmp_path / "kaito" / "settings.json"
        with patch.object(SettingsManager, "_get_path", return_value=cfg):
            sm = SettingsManager()
            assert sm.get("theme") == "system"
            assert sm.get("last_dest") == ""
            assert sm.get("open_on_done") is True
            assert sm.get("compression_level") == 1
            assert sm.get("recent_files") == []

    def test_load_existing(self, tmp_path: Path) -> None:
        cfg = tmp_path / "kaito" / "settings.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({"theme": "dark", "last_dest": "C:\\out"}))
        with patch.object(SettingsManager, "_get_path", return_value=cfg):
            sm = SettingsManager()
            assert sm.get("theme") == "dark"
            assert sm.get("last_dest") == "C:\\out"
            assert sm.get("open_on_done") is True

    def test_set_and_persist(self, tmp_path: Path) -> None:
        cfg = tmp_path / "kaito" / "settings.json"
        with patch.object(SettingsManager, "_get_path", return_value=cfg):
            sm = SettingsManager()
            sm.set("theme", "light")
            assert sm.get("theme") == "light"
            # ファイルに保存されている
            raw = json.loads(cfg.read_text())
            assert raw["theme"] == "light"

    def test_add_recent_file(self, tmp_path: Path) -> None:
        cfg = tmp_path / "kaito" / "settings.json"
        with patch.object(SettingsManager, "_get_path", return_value=cfg):
            sm = SettingsManager()
            sm.add_recent_file("C:\\a.zip")
            sm.add_recent_file("C:\\b.zip")
            assert sm.get("recent_files") == ["C:\\b.zip", "C:\\a.zip"]

    def test_recent_file_dedup(self, tmp_path: Path) -> None:
        cfg = tmp_path / "kaito" / "settings.json"
        with patch.object(SettingsManager, "_get_path", return_value=cfg):
            sm = SettingsManager()
            sm.add_recent_file("C:\\a.zip")
            sm.add_recent_file("C:\\b.zip")
            sm.add_recent_file("C:\\a.zip")  # 重複 → 先頭に移動
            assert sm.get("recent_files") == ["C:\\a.zip", "C:\\b.zip"]

    def test_recent_file_max(self, tmp_path: Path) -> None:
        cfg = tmp_path / "kaito" / "settings.json"
        with patch.object(SettingsManager, "_get_path", return_value=cfg):
            sm = SettingsManager()
            for i in range(MAX_RECENT_FILES + 3):
                sm.add_recent_file(f"C:\\file{i}.zip")
            assert len(sm.get("recent_files")) == MAX_RECENT_FILES

    def test_password_session(self, tmp_path: Path) -> None:
        cfg = tmp_path / "kaito" / "settings.json"
        with patch.object(SettingsManager, "_get_path", return_value=cfg):
            sm = SettingsManager()
            assert sm.get_password("C:\\a.zip") is None
            sm.set_password("C:\\a.zip", "secret")
            assert sm.get_password("C:\\a.zip") == "secret"
            sm.clear_passwords()
            assert sm.get_password("C:\\a.zip") is None

    def test_password_not_persisted(self, tmp_path: Path) -> None:
        cfg = tmp_path / "kaito" / "settings.json"
        with patch.object(SettingsManager, "_get_path", return_value=cfg):
            sm = SettingsManager()
            sm.set_password("C:\\a.zip", "secret")
            sm.save()
            raw = json.loads(cfg.read_text())
            assert "password" not in raw

    def test_save_creates_dir(self, tmp_path: Path) -> None:
        cfg = tmp_path / "nonexistent" / "kaito" / "settings.json"
        with patch.object(SettingsManager, "_get_path", return_value=cfg):
            sm = SettingsManager()
            sm.set("theme", "dark")
            assert cfg.exists()

    def test_corrupted_json(self, tmp_path: Path) -> None:
        cfg = tmp_path / "kaito" / "settings.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text("not json{{{")
        with patch.object(SettingsManager, "_get_path", return_value=cfg):
            sm = SettingsManager()
            assert sm.get("theme") == "system"

    def test_non_dict_json_falls_back(self, tmp_path: Path) -> None:
        """JSONとしては有効でもdictでない設定ファイルはデフォルトにフォールバック"""
        cfg = tmp_path / "kaito" / "settings.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text("[]")
        with patch.object(SettingsManager, "_get_path", return_value=cfg):
            sm = SettingsManager()
            assert sm.get("theme") == "system"
            assert sm.get("dest_mode") == "archive"

    def test_non_dict_json_string_falls_back(self, tmp_path: Path) -> None:
        cfg = tmp_path / "kaito" / "settings.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text('"just a string"')
        with patch.object(SettingsManager, "_get_path", return_value=cfg):
            sm = SettingsManager()
            assert sm.get("theme") == "system"

    def test_invalid_dest_mode_sanitized(self, tmp_path: Path) -> None:
        """dest_modeに不正な値を保存しようとするとデフォルトに戻る"""
        cfg = tmp_path / "kaito" / "settings.json"
        with patch.object(SettingsManager, "_get_path", return_value=cfg):
            sm = SettingsManager()
            sm.set("dest_mode", "evil")
            assert sm.get("dest_mode") == "archive"
            sm.set_many({"dest_mode": "last"})
            assert sm.get("dest_mode") == "last"

    def test_invalid_language_sanitized(self, tmp_path: Path) -> None:
        """languageに不正な値を保存しようとするとデフォルトに戻る"""
        cfg = tmp_path / "kaito" / "settings.json"
        with patch.object(SettingsManager, "_get_path", return_value=cfg):
            sm = SettingsManager()
            assert sm.get("language") == "ja"
            sm.set("language", "fr")
            assert sm.get("language") == "ja"
            sm.set_many({"language": "en"})
            assert sm.get("language") == "en"

    def test_set_many_persists_once(self, tmp_path: Path) -> None:
        """set_many は複数キーを1回のsaveで永続化する"""
        cfg = tmp_path / "kaito" / "settings.json"
        with patch.object(SettingsManager, "_get_path", return_value=cfg):
            sm = SettingsManager()
            with patch.object(sm, "save") as mock_save:
                sm.set_many({"theme": "dark", "dest_mode": "fixed"})
                mock_save.assert_called_once()
                assert sm.get("theme") == "dark"
                assert sm.get("dest_mode") == "fixed"
            sm.save()
            raw = json.loads(cfg.read_text())
            assert raw["theme"] == "dark"
            assert raw["dest_mode"] == "fixed"

    def test_default_dest_mode_and_fixed_dest(self, tmp_path: Path) -> None:
        cfg = tmp_path / "kaito" / "settings.json"
        with patch.object(SettingsManager, "_get_path", return_value=cfg):
            sm = SettingsManager()
            assert sm.get("dest_mode") == "archive"
            assert sm.get("fixed_dest") == ""

    def test_get_with_default(self, tmp_path: Path) -> None:
        cfg = tmp_path / "kaito" / "settings.json"
        with patch.object(SettingsManager, "_get_path", return_value=cfg):
            sm = SettingsManager()
            assert sm.get("nonexistent", "fallback") == "fallback"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows only test")
    def test_get_path_windows(self) -> None:
        with patch.dict(os.environ, {"APPDATA": "C:\\Users\\test\\AppData\\Roaming"}):
            sm = SettingsManager.__new__(SettingsManager)
            path = sm._get_path()
            assert "AppData" in str(path)
            assert path.name == "settings.json"

    def test_get_path_non_windows(self) -> None:
        with (
            patch("sys.platform", "linux"),
            patch("platformdirs.user_config_dir", return_value="/home/user/.config/kaito"),
        ):
            sm = SettingsManager.__new__(SettingsManager)
            path = sm._get_path()
            assert path.name == "settings.json"
            assert "kaito" in str(path)
