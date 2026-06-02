"""
src/kaito/settings.py
設定の永続化 (JSONファイル保存)
関連: unzip_app.py (GUI設定の保持), conftest.py (テスト用パス)
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

DEFAULT_SETTINGS = {
    "theme": "system",
    "last_dest": "",
    "open_on_done": True,
    "recent_files": [],
}

MAX_RECENT_FILES = 10


class SettingsManager:
    """JSONファイルベースの設定管理。パスワードはセッション中のみメモリ保持"""

    def __init__(self) -> None:
        self._path = self._get_path()
        self._data: dict[str, Any] = {}
        self._passwords: dict[str, str] = {}
        self._load()

    def _get_path(self) -> Path:
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", "~/.config"))
        else:  # pragma: no cover (Linux/macOSはCI未対応)
            base = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config"))
        return (base / "kaito").resolve() / "settings.json"

    def _load(self) -> None:
        try:
            raw = self._path.read_text(encoding="utf-8")
            loaded = json.loads(raw)
            self._data = {**DEFAULT_SETTINGS, **loaded}
        except (FileNotFoundError, json.JSONDecodeError):
            self._data = dict(DEFAULT_SETTINGS)

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        self._data[key] = value
        self.save()

    def add_recent_file(self, path: str) -> None:
        recent: list = self._data.setdefault("recent_files", [])
        if path in recent:
            recent.remove(path)
        recent.insert(0, path)
        self._data["recent_files"] = recent[:MAX_RECENT_FILES]
        self.save()

    def get_password(self, zip_path: str) -> str | None:
        return self._passwords.get(zip_path)

    def set_password(self, zip_path: str, password: str) -> None:
        self._passwords[zip_path] = password

    def clear_passwords(self) -> None:
        self._passwords.clear()
