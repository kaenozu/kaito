"""
src/kaito/unzip.py
ZIP/RAR/7zファイルの解凍・圧縮コアロジック
ZIPは標準zipfile、RAR/7zはpatoolibで処理
関連: gui/unzip_app.py (GUIからの呼び出し)
"""

import locale
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

import patoolib
from patoolib.util import PatoolError


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

# ZIPファイルのエンコーディング解決順
# Windows環境（特に日本語）ではCP932でエンコードされたZIPが存在するため、
# UTF-8→システムエンコーディングの順でフォールバックする
_ZIP_ENCODINGS: tuple[str, ...] = ()

# システムロケールに依存しないフォールバック用エンコーディング
# ZIP仕様ではファイル名のエンコーディングが未定義のため、主要言語圏のエンコーディングを
# 総当たりで試す（UTF-8→各国語→システムロケールの順）
_FALLBACK_ENCODINGS = ["utf-8", "cp932", "gbk", "cp949", "euc-kr"]


def get_zip_encodings() -> tuple[str, ...]:
    """ZIPファイル名のデコードに試すエンコーディング一覧

    UTF-8を最優先し、次に主要な東アジアエンコーディング(CP932/GBK/CP949)、
    最後にシステムロケールのエンコーディングを試す。
    """
    global _ZIP_ENCODINGS
    if not _ZIP_ENCODINGS:
        seen: set[str] = set()
        encodings: list[str] = []
        for enc in _FALLBACK_ENCODINGS:
            if enc not in seen:
                seen.add(enc)
                encodings.append(enc)
        try:
            sys_enc = locale.getencoding()
            sys_lower = sys_enc.lower()
            if sys_lower not in (e.lower() for e in seen):
                encodings.append(sys_enc)
        except Exception:
            pass
        _ZIP_ENCODINGS = tuple(encodings)
    return _ZIP_ENCODINGS


def _has_surrogates(names: list[str]) -> bool:
    """文字列リストにサロゲート文字（デコード失敗の跡）が含まれるか判定"""
    for name in names:
        for c in name:
            if 0xDC80 <= ord(c) <= 0xDCFF:
                return True
    return False


def _encoding_tries() -> list[str]:
    """試行するエンコーディングの優先順位一覧

    UTF-8 を最優先し、フォールバックエンコーディング（CP932等）を試す。
    デフォルト（metadata_encoding=None）は ZIP 仕様の CP437 相当になり、
    日本語ZIPではほぼ確実に誤った結果になるため使用しない。
    """
    tries: list[str] = ["utf-8"]
    for enc in get_zip_encodings():
        if enc.lower() not in ("utf-8", "utf8"):
            tries.append(enc)
    return tries


def try_zip_with_encodings[T](
    zip_path: str | Path,
    operation: Callable[[zipfile.ZipFile], T],
) -> T:
    """エンコーディングフォールバック付きでZIP操作を実行

    UTF-8を最優先し、サロゲート文字（Python 3.12+が誤ったエンコーディング時に
    挿入する \\uDC80-\\uDCFF）がなければその結果を採用する。
    全エンコーディングでサロゲートが発生した場合でも、最後の試行結果を強制採用する。

    Args:
        zip_path: ZIPファイルパス
        operation: ZipFileを受け取り結果を返す関数

    Returns:
        operationの結果

    Raises:
        RuntimeError: 全エンコーディングで失敗した場合
    """
    opened: list[zipfile.ZipFile] = []
    try:
        for enc in _encoding_tries():
            try:
                zf = zipfile.ZipFile(zip_path, "r", metadata_encoding=enc)
            except (UnicodeDecodeError, UnicodeError, LookupError):
                continue
            opened.append(zf)
            names = [e.filename for e in zf.infolist()]
            if not _has_surrogates(names):
                return operation(zf)
        # 全エンコーディングでサロゲート発生 → 最後の結果を強制採用
        if opened:
            return operation(opened[-1])
        raise RuntimeError("ZIPファイルを開けませんでした")
    finally:
        for zf in opened:
            zf.close()


def create_archive(
    sources: list[Path],
    output: Path,
    on_progress: ProgressCallback | None = None,
    compression_level: int = 1,
) -> None:
    """アーカイブを作成する

    Args:
        sources: 圧縮対象のファイル/ディレクトリパス
        output: 出力アーカイブパス（拡張子で形式決定）
        on_progress: 進捗コールバック (current, total, name)
    """
    ext = output.suffix.lower()
    if ext == ".zip":
        if not 0 <= compression_level <= 9:
            raise ValueError("圧縮レベルは0〜9で指定してください")
        _create_zip(sources, output, on_progress, compression_level)
    elif ext in ARCHIVE_EXTENSIONS:
        try:
            patoolib.create_archive(str(output), [str(s) for s in sources])
        except (OSError, RuntimeError, PatoolError) as e:
            raise RuntimeError(f"アーカイブの作成に失敗しました: {e}")
    else:
        raise ValueError(f"未対応のアーカイブ形式です: {ext}")


def _create_zip(
    sources: list[Path],
    output: Path,
    on_progress: ProgressCallback | None = None,
    compression_level: int = 1,
) -> None:
    """ZIPアーカイブを作成"""
    # 個別ファイル単位で進捗を計算するため総ファイル数をカウント
    total = 0
    for s in sources:
        if s.is_dir():
            total += sum(1 for f in s.rglob("*") if f.is_file())
        else:
            total += 1
    done = 0
    # Python 3.12+のzipfileはデフォルトでUTF-8を使用する
    # レベル1は標準のレベル6より大幅に速く、通常のファイルでは十分な圧縮率を保つ。
    with zipfile.ZipFile(
        output, "w", zipfile.ZIP_DEFLATED, compresslevel=compression_level
    ) as zf:
        for source in sources:
            if source.is_dir():
                for f in source.rglob("*"):
                    arcname = f.relative_to(source.parent)
                    if f.is_file():
                        zf.write(f, str(arcname))
                        done += 1
                        if on_progress:
                            on_progress(done, total, f.name)
                    elif f.is_dir():
                        zi = zipfile.ZipInfo(str(arcname) + "/")
                        zf.writestr(zi, "")
            else:
                zf.write(source, source.name)
                done += 1
                if on_progress:
                    on_progress(done, total, source.name)


def is_supported(path: str | Path) -> bool:
    """対応アーカイブ形式かを判定"""
    return Path(path).suffix.lower() in ARCHIVE_EXTENSIONS


def list_archive(
    path: str | Path,
    _password: str | None = None,
) -> tuple[list[ZipEntry], bool]:
    """アーカイブの内容一覧を返す

    ZIPは常に一覧可能。RAR/7zは暗号化されていると空の一覧+暗号化フラグを返す。
    _passwordはRAR/7zではpatoolib.list_archiveが非対応なため実質利用しないが、
    extract_archiveとのAPI一貫性のために受け付ける。
    """
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
        ZipEntry(
            name=n,
            size=0,
            compressed_size=0,
            modified=datetime.now(),
            is_dir=n.endswith("/"),
        )
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
        except (OSError, RuntimeError, PatoolError) as e:
            raise RuntimeError(f"アーカイブの展開に失敗しました: {e}")
    else:
        raise ValueError(f"未対応のアーカイブ形式です: {ext}")


def list_entries(zip_path: str | Path) -> tuple[list[ZipEntry], bool]:
    """ZIPファイルの内容一覧を返す。戻り値: (entries, is_encrypted)

    日本語Windowsで作成されたCP932エンコードのZIPに備え、
    UTF-8で失敗した場合はシステムエンコーディングで再試行する。
    暗号化検出は general purpose bit flag の bit0 (ZipCrypto) および
    bit6 (強力暗号化 / AES) を確認する。
    """

    def _extract_entries(zf: zipfile.ZipFile) -> tuple[list[ZipEntry], bool]:
        entries: list[ZipEntry] = []
        is_encrypted = False
        for info in zf.infolist():
            _ = info.filename  # デコードをトリガー
            if info.flag_bits & 0x1 or info.flag_bits & 0x40:
                is_encrypted = True
            try:
                modified = datetime(*info.date_time)
            except ValueError:
                # 壊れたアーカイブの不正日時（月=0等）は現在時刻にフォールバック
                modified = datetime.now()
            entries.append(
                ZipEntry(
                    name=info.filename,
                    size=info.file_size,
                    compressed_size=info.compress_size,
                    modified=modified,
                    is_dir=info.filename.endswith("/"),
                )
            )
        return entries, is_encrypted

    return try_zip_with_encodings(zip_path, _extract_entries)


def _validate_entry_path(dest: str | Path, name: str) -> None:
    """ZIPエントリ名が展開先ディレクトリの外へ出ないことを検証する

    Path traversal攻撃（ZIP slip）対策。ファイル・ディレクトリ両方の
    エントリに適用する。resolve() 後のパスが dest の厳密な子孫か
    is_relative_to で判定する（文字列のstartswith比較は
    ``out`` と ``out_evil`` を誤判定するため使わない）。
    """
    dest_resolved = Path(dest).resolve()
    target_path = (dest_resolved / name).resolve()
    if not target_path.is_relative_to(dest_resolved):
        raise RuntimeError(f"安全でないパスが含まれています: {name}")


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

    def _do_extract(zf: zipfile.ZipFile) -> None:
        if password is not None:
            zf.setpassword(password.encode("utf-8"))

        targets = members or [e.filename for e in zf.infolist()]
        total = len(targets)

        for i, name in enumerate(targets):
            # Path traversal攻撃対策: ディレクトリ/ファイル両方のパスを検証
            _validate_entry_path(dest, name)
            # ディレクトリエントリは作成のみ
            if name.endswith("/"):
                (Path(dest) / name).mkdir(parents=True, exist_ok=True)
            else:
                zf.extract(name, str(dest))

            if on_progress:
                on_progress(i + 1, total, name)

    try_zip_with_encodings(zip_path, _do_extract)


def extract_all(
    zip_path: str | Path,
    dest: str | Path,
    password: str | None = None,
    on_progress: ProgressCallback | None = None,
) -> None:
    """全エントリを展開（extract に委譲、members=Noneですべて展開）"""
    extract(
        zip_path,
        dest,
        password=password,
        on_progress=on_progress,
        members=None,
    )
