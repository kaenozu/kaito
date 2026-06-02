"""
src/kaito/crack.py
パスワード付きZIPのパスワード復元（辞書＋ルールベース）
関連: gui/unzip_app.py (このモジュールを呼ぶGUI), unzip.py
"""

import re
import zipfile
from datetime import date
from pathlib import Path
from typing import Callable

# よく使われるパスワード（日本語・英語 上位）
_COMMON_PASSWORDS: list[str] = [
    "password", "123456", "12345678", "1234", "qwerty", "abc123",
    "password123", "admin", "letmein", "welcome", "monkey", "dragon",
    "passw0rd", "master", "sunshine", "princess", "football", "iloveyou",
    "trustno1", "shadow", "superman", "batman", "access", "hello",
    "charlie", "donald", "mustang", "pass", "123456789", "qwerty123",
    "zaq1xsw2", "1qaz2wsx", "qazwsx", "qwertyuiop", "asdfghjkl",
    "zxcvbnm", "0987654321", "147258369", "112233", "123321",
    # 日本語
    "password", "pass", "p@s5w0rd", "passw0rd",
    "1234", "0000", "1111", "2222", "3333", "4444", "5555",
    "6666", "7777", "8888", "9999", "1212",
    "test", "guest", "user", "sample", "default",
]

# 年・月・日に関する単語
_SEASONAL_WORDS: list[str] = [
    "spring", "summer", "autumn", "fall", "winter",
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
    "mon", "tue", "wed", "thu", "fri", "sat", "sun",
    "monday", "tuesday", "wednesday", "thursday", "friday",
    "saturday", "sunday",
]


def generate_candidates(
    zip_path: Path,
    hint: str = "",
) -> list[str]:
    """パスワード候補を生成する"""
    candidates: list[str] = []
    seen: set[str] = set()

    def add(pw: str) -> None:
        pw_lower = pw.lower()
        if pw_lower not in seen and len(pw) >= 1:
            seen.add(pw_lower)
            candidates.append(pw)

    # ヒントをそのまま
    if hint:
        add(hint)

    # ZIPファイル名から単語を抽出
    stem_words = _extract_words(zip_path.stem)
    for w in stem_words:
        add(w)

    # 中身のファイル名から単語を抽出
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                for w in _extract_words(Path(info.filename).stem):
                    add(w)
                # 日付から候補
                if info.date_time != (0, 0, 0, 0, 0, 0):
                    y, m, d, *_ = info.date_time
                    add(f"{y}")
                    add(f"{y}{m:02d}")
                    add(f"{y}{m:02d}{d:02d}")
                    add(f"{m:02d}{d:02d}")
                    if m <= 12 and d <= 31:
                        add(f"{m}{d}")
    except Exception:
        pass

    # 今日の日付
    today = date.today()
    add(f"{today.year}")
    add(f"{today.year}{today.month:02d}")
    add(f"{today.year}{today.month:02d}{today.day:02d}")
    add(f"{today.month:02d}{today.day:02d}")

    # 一般的なパスワード
    for pw in _COMMON_PASSWORDS:
        add(pw)

    # 季節・月の単語
    for w in _SEASONAL_WORDS:
        add(w)

    # ヒントから派生
    if hint:
        add(hint.swapcase())
        add(hint.upper())
        add(hint + "1")
        add(hint + "!")
        add(hint + "123")
        add(hint + str(date.today().year))
        add(hint[::-1])

    # 数字パターン
    for n in range(0, 100):
        add(f"{n:02d}")
    for n in [100, 123, 200, 1000, 2000, 2020, 2021, 2022, 2023, 2024]:
        add(str(n))

    return candidates


def _extract_words(text: str) -> list[str]:
    """テキストから英数字の単語を抽出"""
    words: list[str] = []
    for part in re.split(r"[_\-\s.]+", text):
        if part and len(part) >= 2:
            words.append(part)
            # 大文字小文字のバリエーション
            if part.islower():
                words.append(part.capitalize())
                words.append(part.upper())
            elif part.isupper():
                words.append(part.lower())
                words.append(part.capitalize())
            elif part[0].isupper():
                words.append(part.lower())
    return words


ProgressCallback = Callable[[int, int], None]


def try_crack(
    zip_path: Path,
    candidates: list[str],
    on_progress: ProgressCallback | None = None,
) -> str | None:
    """パスワード候補を順に試行し、見つかったら返す"""
    total = len(candidates)
    for i, pw in enumerate(candidates):
        if on_progress:
            on_progress(i + 1, total)

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.setpassword(pw.encode("utf-8"))
                zf.testzip()
        except (RuntimeError, zipfile.BadZipFile):
            continue
        except Exception:
            continue

        # testzip() が成功したら正解
        return pw

    return None
