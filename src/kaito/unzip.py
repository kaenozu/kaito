"""
src/kaito/unzip.py
ZIPファイル解凍のコアロジック
Python標準のzipfileモジュールで解凍処理を行う
関連: gui/unzip_app.py (このモジュールを呼ぶGUI)
"""

import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol


@dataclass
class ZipEntry:
    """ZIP内の1エントリの情報"""
    name: str
    size: int
    compressed_size: int
    modified: datetime
    is_dir: bool


ProgressCallback = Callable[[int, int, str], None]
"""進捗コールバック: (current, total, current_name)"""


class PasswordPrompt(Protocol):
    """パスワード入力のためのプロトコル"""
    def __call__(self) -> str | None: ...


def list_entries(zip_path: str | Path) -> tuple[list[ZipEntry], bool]:
    """ZIPファイルの内容一覧を返す。戻り値: (entries, is_encrypted)"""
    entries: list[ZipEntry] = []
    is_encrypted = False
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            # general purpose bit flagのbit0: 暗号化フラグ
            if info.flag_bits & 0x1:
                is_encrypted = True
            entries.append(ZipEntry(
                name=info.filename,
                size=info.file_size,
                compressed_size=info.compress_size,
                modified=datetime(*info.date_time),
                is_dir=info.filename.endswith("/"),
            ))
    return entries, is_encrypted


def extract(
    zip_path: str | Path,
    dest: str | Path,
    password: str | None = None,
    on_progress: ProgressCallback | None = None,
    members: list[str] | None = None,
) -> None:
    """ZIPファイルを展開する

    Args:
        zip_path: ZIPファイルのパス
        dest: 展開先ディレクトリ
        password: パスワード（必要な場合）
        on_progress: 進捗コールバック (current, total)
        members: 展開するエントリ名のリスト（None=すべて）
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        if password is not None:
            zf.setpassword(password.encode("utf-8"))

        targets = members or [e.filename for e in zf.infolist()]
        total = len(targets)

        for i, name in enumerate(targets):
            # ディレクトリエントリは作成のみ
            if name.endswith("/"):
                (Path(dest) / name).mkdir(parents=True, exist_ok=True)
            else:
                zf.extract(name, str(dest))

            if on_progress:
                on_progress(i + 1, total, name)


def extract_all(
    zip_path: str | Path,
    dest: str | Path,
    password: str | None = None,
    on_progress: ProgressCallback | None = None,
) -> None:
    """全エントリを展開（list_entries → extract のショートカット）"""
    entries, _ = list_entries(zip_path)
    extract(
        zip_path, dest, password=password, on_progress=on_progress,
        members=[e.name for e in entries],
    )
