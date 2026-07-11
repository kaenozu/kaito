"""kaitoのバージョン取得。"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


def get_version() -> str:
    """インストール済みパッケージメタデータからバージョンを返す。"""
    try:
        return version("kaito")
    except PackageNotFoundError:
        # ソースファイルだけを直接実行した場合の診断用フォールバック。
        return "0+unknown"


__version__ = get_version()
