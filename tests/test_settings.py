"""SettingsManagerの永続化・検証テスト。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from kaito.domain.models import SafetyLimits
from kaito.settings import MAX_RECENT_FILES, SettingsManager


class TestSettingsManager:
    def test_defaults_on_missing_file(self, tmp_path: Path) -> None:
        config = tmp_path / "kaito" / "settings.json"
        with patch.object(SettingsManager, "_get_path", return_value=config):
            settings = SettingsManager()
            assert settings.get("theme") == "system"
            assert settings.get("last_dest") == ""
            assert settings.get("open_on_done") is True
            assert settings.get("compression_level") == 1
            assert settings.get("recent_files") == []

    def test_load_existing(self, tmp_path: Path) -> None:
        config = tmp_path / "kaito" / "settings.json"
        config.parent.mkdir(parents=True)
        config.write_text(
            json.dumps({"theme": "dark", "last_dest": "C:\\out"}),
            encoding="utf-8",
        )
        with patch.object(SettingsManager, "_get_path", return_value=config):
            settings = SettingsManager()
            assert settings.get("theme") == "dark"
            assert settings.get("last_dest") == "C:\\out"
            assert settings.get("open_on_done") is True

    def test_set_and_persist(self, tmp_path: Path) -> None:
        config = tmp_path / "kaito" / "settings.json"
        with patch.object(SettingsManager, "_get_path", return_value=config):
            settings = SettingsManager()
            settings.set("theme", "light")
            assert settings.get("theme") == "light"
            raw = json.loads(config.read_text(encoding="utf-8"))
            assert raw["theme"] == "light"

    def test_add_recent_file(self, tmp_path: Path) -> None:
        config = tmp_path / "kaito" / "settings.json"
        with patch.object(SettingsManager, "_get_path", return_value=config):
            settings = SettingsManager()
            settings.add_recent_file("C:\\a.zip")
            settings.add_recent_file("C:\\b.zip")
            assert settings.get("recent_files") == ["C:\\b.zip", "C:\\a.zip"]

    def test_recent_file_dedup_is_case_insensitive(self, tmp_path: Path) -> None:
        config = tmp_path / "kaito" / "settings.json"
        with patch.object(SettingsManager, "_get_path", return_value=config):
            settings = SettingsManager()
            settings.add_recent_file("C:\\Folder\\A.zip")
            settings.add_recent_file("c:/folder/a.ZIP")
            assert settings.get("recent_files") == ["c:/folder/a.ZIP"]

    def test_recent_file_max(self, tmp_path: Path) -> None:
        config = tmp_path / "kaito" / "settings.json"
        with patch.object(SettingsManager, "_get_path", return_value=config):
            settings = SettingsManager()
            for index in range(MAX_RECENT_FILES + 3):
                settings.add_recent_file(f"C:\\file{index}.zip")
            assert len(settings.get("recent_files")) == MAX_RECENT_FILES

    def test_password_session(self, tmp_path: Path) -> None:
        config = tmp_path / "kaito" / "settings.json"
        with patch.object(SettingsManager, "_get_path", return_value=config):
            settings = SettingsManager()
            assert settings.get_password("C:\\a.zip") is None
            settings.set_password("C:\\a.zip", "secret")
            assert settings.get_password("C:\\a.zip") == "secret"
            settings.clear_passwords()
            assert settings.get_password("C:\\a.zip") is None

    def test_password_not_persisted(self, tmp_path: Path) -> None:
        config = tmp_path / "kaito" / "settings.json"
        with patch.object(SettingsManager, "_get_path", return_value=config):
            settings = SettingsManager()
            settings.set_password("C:\\a.zip", "secret")
            settings.save()
            raw = json.loads(config.read_text(encoding="utf-8"))
            assert "password" not in raw
            assert "secret" not in config.read_text(encoding="utf-8")

    def test_save_creates_dir(self, tmp_path: Path) -> None:
        config = tmp_path / "nonexistent" / "kaito" / "settings.json"
        with patch.object(SettingsManager, "_get_path", return_value=config):
            settings = SettingsManager()
            settings.set("theme", "dark")
            assert config.exists()

    def test_corrupted_json(self, tmp_path: Path) -> None:
        config = tmp_path / "kaito" / "settings.json"
        config.parent.mkdir(parents=True)
        config.write_text("not json{{{", encoding="utf-8")
        with patch.object(SettingsManager, "_get_path", return_value=config):
            settings = SettingsManager()
            assert settings.get("theme") == "system"

    @pytest.mark.parametrize("root", [[], "text", 123, True, None])
    def test_valid_json_with_non_object_root_uses_defaults(
        self, root: object, tmp_path: Path
    ) -> None:
        config = tmp_path / "kaito" / "settings.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps(root), encoding="utf-8")
        with patch.object(SettingsManager, "_get_path", return_value=config):
            settings = SettingsManager()
            assert settings.get("theme") == "system"
            assert settings.get("recent_files") == []

    def test_invalid_values_are_reset_individually(self, tmp_path: Path) -> None:
        config = tmp_path / "kaito" / "settings.json"
        config.parent.mkdir(parents=True)
        config.write_text(
            json.dumps(
                {
                    "theme": "neon",
                    "language": "unknown",
                    "open_on_done": 1,
                    "compression_level": 99,
                    "recent_files": ["a.zip", 1, "A.ZIP", ""],
                    "safety_max_entries": -1,
                    "safety_max_compression_ratio": 0,
                }
            ),
            encoding="utf-8",
        )
        with patch.object(SettingsManager, "_get_path", return_value=config):
            settings = SettingsManager()
            assert settings.get("theme") == "system"
            assert settings.get("language") == "ja"
            assert settings.get("open_on_done") is True
            assert settings.get("compression_level") == 1
            assert settings.get("recent_files") == ["a.zip"]
            assert settings.get("safety_max_entries") == SafetyLimits.max_entries
            assert (
                settings.get("safety_max_compression_ratio")
                == SafetyLimits.max_compression_ratio
            )

    def test_default_recent_lists_are_not_shared(self, tmp_path: Path) -> None:
        first_config = tmp_path / "first" / "settings.json"
        second_config = tmp_path / "second" / "settings.json"
        with patch.object(SettingsManager, "_get_path", return_value=first_config):
            first = SettingsManager()
        with patch.object(SettingsManager, "_get_path", return_value=second_config):
            second = SettingsManager()

        first.get("recent_files").append("mutated.zip")

        assert second.get("recent_files") == []

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
        config = tmp_path / "kaito" / "settings.json"
        with patch.object(SettingsManager, "_get_path", return_value=config):
            settings = SettingsManager()
            assert settings.get("nonexistent", "fallback") == "fallback"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows only test")
    def test_get_path_windows(self) -> None:
        with patch.dict(os.environ, {"APPDATA": "C:\\Users\\test\\AppData\\Roaming"}):
            settings = SettingsManager.__new__(SettingsManager)
            path = settings._get_path()
            assert "AppData" in str(path)
            assert path.name == "settings.json"

    def test_get_path_non_windows(self) -> None:
        with (
            patch("sys.platform", "linux"),
            patch(
                "platformdirs.user_config_dir", return_value="/home/user/.config/kaito"
            ),
        ):
            settings = SettingsManager.__new__(SettingsManager)
            path = settings._get_path()
            assert path.name == "settings.json"
            assert "kaito" in str(path)
