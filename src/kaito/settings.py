"""
src/kaito/settings.py
設定の永続化 (JSONファイル保存) + スキーマ検証
関連: gui/unzip_app.py, gui/settings_dialog.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

import platformdirs

from kaito.domain.models import SafetyLimits

# デフォルト設定
DEFAULT_SETTINGS = {
    "theme": "system",
    "language": "日本語",
    "last_dest": "",
    "open_on_done": True,
    "close_on_done": False,
    "recent_files": [],
    "compression_level": 1,
}

MAX_RECENT_FILES = 10

# 設定スキーマ (キー → (期待する型, デフォルト値))
_SETTINGS_SCHEMA: dict[str, tuple[type, Any]] = {
    "theme": (str, "system"),
    "language": (str, "日本語"),
    "last_dest": (str, ""),
    "open_on_done": (bool, True),
    "close_on_done": (bool, False),
    "recent_files": (list, []),
    "compression_level": (int, 1),
    "safety_max_entries": (int, SafetyLimits.max_entries),
    "safety_max_total_size": (int, SafetyLimits.max_total_size),
    "safety_max_file_size": (int, SafetyLimits.max_single_file_size),
    "safety_max_compression_ratio": (float, SafetyLimits.max_compression_ratio),
}


def _validate_settings(data: dict[str, Any]) -> dict[str, Any]:
    """設定値をスキーマで検証し、不正な値だけデフォルトへ戻す"""
    validated: dict[str, Any] = {}
    for key, (expected_type, default) in _SETTINGS_SCHEMA.items():
        value = data.get(key, default)
        if not isinstance(value, expected_type):
            validated[key] = default
        else:
            validated[key] = value
    # スキーマ外のキーは無視
    return validated


class SettingsManager:
    """JSONファイルベースの設定管理。パスワードはセッション中のみメモリ保持"""

    def __init__(self) -> None:
        self._path = self._get_path()
        self._data: dict[str, Any] = {}
        self._passwords: dict[str, str] = {}
        self._dirty = False
        self._load()

    def _get_path(self) -> Path:
        if sys.platform == "win32":
            base = Path(platformdirs.user_config_dir("kaito", roaming=True))
        else:
            base = Path(platformdirs.user_config_dir("kaito"))
        return base / "settings.json"

    def _load(self) -> None:
        try:
            raw = self._path.read_text(encoding="utf-8")
            loaded = json.loads(raw)
            self._data = _validate_settings(loaded)
        except (
            FileNotFoundError,
            json.JSONDecodeError,
            PermissionError,
            OSError,
            UnicodeDecodeError,
        ):
            self._data = dict(DEFAULT_SETTINGS)

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # 原子的に保存: 一時ファイルに書き込んでからリネーム
        try:
            tmp = self._path.parent / f".settings.{id(self)}.tmp"
            tmp.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(self._path)
            self._dirty = False
        except (PermissionError, OSError) as e:
            raise RuntimeError(f"設定の保存に失敗しました: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._dirty = True
        self.save()

    def set_many(self, **kwargs: Any) -> None:
        """複数設定をまとめて更新し、1度だけ保存"""
        self._data.update(kwargs)
        self._dirty = True
        self.save()

    def save_now(self) -> None:
        """直ちにディスクに保存"""
        self.save()

    def add_recent_file(self, path: str) -> None:
        recent: list = self._data.setdefault("recent_files", [])
        if path in recent:
            recent.remove(path)
        recent.insert(0, path)
        self._data["recent_files"] = recent[:MAX_RECENT_FILES]
        self._dirty = True
        self.save()

    def get_password(self, zip_path: str) -> Optional[str]:
        return self._passwords.get(zip_path)

    def set_password(self, zip_path: str, password: str) -> None:
        self._passwords[zip_path] = password

    def clear_passwords(self) -> None:
        self._passwords.clear()
