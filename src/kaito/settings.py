"""JSONベースの設定永続化とスキーマ検証。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

import platformdirs

from kaito.domain.models import SafetyLimits

DEFAULT_SETTINGS: dict[str, Any] = {
    "theme": "system",
    "language": "日本語",
    "last_dest": "",
    "open_on_done": True,
    "close_on_done": False,
    "recent_files": [],
    "compression_level": 1,
    "safety_max_entries": SafetyLimits.max_entries,
    "safety_max_total_size": SafetyLimits.max_total_size,
    "safety_max_file_size": SafetyLimits.max_single_file_size,
    "safety_max_compression_ratio": SafetyLimits.max_compression_ratio,
    "safety_max_path_length": SafetyLimits.max_path_length,
}

MAX_RECENT_FILES = 10
_ALLOWED_THEMES = frozenset({"system", "light", "dark"})
_ALLOWED_LANGUAGES = frozenset({"日本語", "English"})


def _defaults() -> dict[str, Any]:
    """可変値を共有しない既定設定を返す。"""
    return deepcopy(DEFAULT_SETTINGS)


def _positive_int(value: object, default: int, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return default
    if maximum is not None and value > maximum:
        return default
    return value


def _validate_recent_files(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            continue
        normalized_key = item.replace("/", "\\").casefold()
        if normalized_key in seen:
            continue
        seen.add(normalized_key)
        result.append(item)
        if len(result) >= MAX_RECENT_FILES:
            break
    return result


def _validate_settings(data: object) -> dict[str, Any]:
    """設定値を検証し、不正な値だけ既定値へ戻す。"""
    if not isinstance(data, dict):
        return _defaults()

    defaults = _defaults()
    theme = data.get("theme")
    defaults["theme"] = theme if theme in _ALLOWED_THEMES else "system"

    language = data.get("language")
    defaults["language"] = language if language in _ALLOWED_LANGUAGES else "日本語"

    last_dest = data.get("last_dest")
    defaults["last_dest"] = last_dest if isinstance(last_dest, str) else ""

    for key in ("open_on_done", "close_on_done"):
        value = data.get(key)
        defaults[key] = value if isinstance(value, bool) else DEFAULT_SETTINGS[key]

    defaults["recent_files"] = _validate_recent_files(data.get("recent_files"))

    compression_level = data.get("compression_level")
    defaults["compression_level"] = (
        compression_level
        if isinstance(compression_level, int)
        and not isinstance(compression_level, bool)
        and 0 <= compression_level <= 9
        else 1
    )

    defaults["safety_max_entries"] = _positive_int(
        data.get("safety_max_entries"), SafetyLimits.max_entries, maximum=1_000_000
    )
    defaults["safety_max_total_size"] = _positive_int(
        data.get("safety_max_total_size"),
        SafetyLimits.max_total_size,
        maximum=100 * 1024 * 1024 * 1024,
    )
    defaults["safety_max_file_size"] = _positive_int(
        data.get("safety_max_file_size"),
        SafetyLimits.max_single_file_size,
        maximum=100 * 1024 * 1024 * 1024,
    )
    ratio = data.get("safety_max_compression_ratio")
    defaults["safety_max_compression_ratio"] = (
        float(ratio)
        if isinstance(ratio, (int, float))
        and not isinstance(ratio, bool)
        and 1.0 <= float(ratio) <= 100_000.0
        else SafetyLimits.max_compression_ratio
    )
    defaults["safety_max_path_length"] = _positive_int(
        data.get("safety_max_path_length"),
        SafetyLimits.max_path_length,
        maximum=32_767,
    )
    return defaults


class SettingsManager:
    """設定ファイルとセッション内パスワードを管理する。"""

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
            loaded = json.loads(self._path.read_text(encoding="utf-8"))
            self._data = _validate_settings(loaded)
        except (
            FileNotFoundError,
            json.JSONDecodeError,
            PermissionError,
            OSError,
            UnicodeDecodeError,
        ):
            self._data = _defaults()

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        descriptor: int | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".settings.", suffix=".tmp", dir=self._path.parent
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                descriptor = None
                json.dump(self._data, stream, indent=2, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            temporary_path.replace(self._path)
            temporary_path = None
            self._dirty = False
        except (PermissionError, OSError) as exc:
            raise RuntimeError(f"設定の保存に失敗しました: {exc}") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.set_many(**{key: value})

    def set_many(self, **kwargs: Any) -> None:
        """複数設定をまとめて検証・更新し、1度だけ保存する。"""
        proposed = dict(self._data)
        proposed.update(kwargs)
        self._data = _validate_settings(proposed)
        self._dirty = True
        self.save()

    def save_now(self) -> None:
        self.save()

    def add_recent_file(self, path: str) -> None:
        if not isinstance(path, str) or not path.strip():
            return
        current = [path, *self._data.get("recent_files", [])]
        self._data["recent_files"] = _validate_recent_files(current)
        self._dirty = True
        self.save()

    def get_password(self, zip_path: str) -> Optional[str]:
        return self._passwords.get(zip_path)

    def set_password(self, zip_path: str, password: str) -> None:
        self._passwords[zip_path] = password

    def clear_passwords(self) -> None:
        self._passwords.clear()
