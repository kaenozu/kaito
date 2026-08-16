"""ZIPファイル名のエンコーディング解決（leaf モジュール）。

7-Zip (IInArchive) は UTF-8 フラグのない ZIP 名をシステムのコードページで
デコードするため、CP932 等の日本語 ZIP を英語ロケールで読むと mojibake に
なる。旧 zipfile 読み取り系と同じフォールバックを DLL バックエンドでも
使えるよう、依存のない場所に切り出している。
"""

from __future__ import annotations

_ZIP_ENCODINGS: tuple[str, ...] = ()
_FALLBACK_ENCODINGS = ["utf-8", "cp932", "gbk", "cp949", "shift_jis", "euc-kr"]


def get_zip_encodings() -> tuple[str, ...]:
    """ZIPファイル名のデコードに試すエンコーディング一覧"""
    global _ZIP_ENCODINGS
    if not _ZIP_ENCODINGS:
        import locale

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
