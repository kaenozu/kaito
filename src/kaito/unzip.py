"""
src/kaito/unzip.py
ZIP/RAR/7zファイル解凍のコアロジック
ZIPは標準zipfile、RAR/7zはpatoolibで処理
関連: gui/unzip_app.py (このモジュールを呼ぶGUI)
"""

import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

import patoolib


@dataclass
class ZipEntry:
    """アーカイブ内の1エントリの情報"""
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


ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z"}


def is_supported(path: str | Path) -> bool:
    """対応アーカイブ形式かを判定"""
    return Path(path).suffix.lower() in ARCHIVE_EXTENSIONS


def list_archive(
    path: str | Path,
    password: str | None = None,
) -> tuple[list[ZipEntry], bool]:
    """アーカイブの内容一覧を返す

    ZIPは常に一覧可能。RAR/7zは暗号化されていると空の一覧+暗号化フラグを返す。
    passwordはRAR/7zではpatoolib.list_archiveが非対応なため実質利用しないが、
    extract_archiveとのAPI一貫性のために受け付ける。
    """
    # RAR/7zのlist_archiveはpatoolib経由でpassword非対応のため破棄
    del password  # noqa: F841 (API一貫性のために接受的)
    ext = Path(path).suffix.lower()
    if ext == ".zip":
        return list_entries(path)
    elif ext in ARCHIVE_EXTENSIONS:
        return _list_patool_archive(path)
    else:
        raise ValueError(f"未対応のアーカイブ形式です: {ext}")


def _list_patool_archive(path: str | Path) -> tuple[list[ZipEntry], bool]:
    """patoolibでアーカイブの内容一覧を取得（非ZIP形式）"""
    try:
        names = patoolib.list_archive(str(path)) or []
    except Exception as e:
        msg = str(e).lower()
        if "password" in msg or "encrypted" in msg:
            return [], True
        raise RuntimeError(f"アーカイブの一覧取得に失敗しました: {e}")
    entries = [
        ZipEntry(name=n, size=0, compressed_size=0, modified=datetime.now(), is_dir=n.endswith("/"))
        for n in names
    ]
    return entries, False


def extract_archive(
    path: str | Path,
    dest: str | Path,
    password: str | None = None,
    on_progress: ProgressCallback | None = None,
) -> None:
    """アーカイブを展開する"""
    ext = Path(path).suffix.lower()
    if ext == ".zip":
        extract_all(path, dest, password=password, on_progress=on_progress)
    elif ext in ARCHIVE_EXTENSIONS:
        try:
            patoolib.extract_archive(str(path), outdir=str(dest), password=password)
        except Exception as e:
            raise RuntimeError(f"アーカイブの展開に失敗しました: {e}")
    else:
        raise ValueError(f"未対応のアーカイブ形式です: {ext}")


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
