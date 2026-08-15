"""
tools/gen_mock_i18n.py
preview/index.html の I18N 辞書を src/kaito/i18n.py の STRINGS から生成する。

モックの UI 文言の単一ソースはアプリ本体 (kaito/i18n.py)。このスクリプトを
実行すると index.html 内の GENERATED_I18N マーカー間が再生成される。

使い方:
    uv run python tools/gen_mock_i18n.py

検証 (再生成後に辞書が最新か確認):
    uv run python tools/gen_mock_i18n.py --check
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from kaito.i18n import STRINGS

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "preview" / "index.html"

START = "// [GENERATED_I18N_START]"
END = "// [GENERATED_I18N_END]"

_PATTERN = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)


def _render() -> str:
    """STRINGS 辞書 → マーカー付き JS ブロック"""
    lines = [
        START,
        "// 生成元: src/kaito/i18n.py (STRINGS) — 手編集禁止。再生成: uv run python tools/gen_mock_i18n.py",
        "const I18N = {",
    ]
    for key in sorted(STRINGS["ja"]):
        ja = STRINGS["ja"][key]
        en = STRINGS["en"].get(key, ja)  # 欠落時は ja で補完（アプリの tr() と同様）
        lines.append(
            f"  {json.dumps(key, ensure_ascii=False)}: "
            f"{{ ja: {json.dumps(ja, ensure_ascii=False)}, en: {json.dumps(en, ensure_ascii=False)} }},"
        )
    lines += ["};", END]
    return "\n".join(lines)


def main() -> int:
    html = INDEX.read_text(encoding="utf-8")
    if not _PATTERN.search(html):
        print(
            f"error: マーカー {START!r} / {END!r} が {INDEX} に見つかりません",
            file=sys.stderr,
        )
        return 1

    generated = _render()
    if "--check" in sys.argv:
        current = _PATTERN.search(html).group(0)
        if current == generated:
            print(f"OK: {len(STRINGS['ja'])} keys - index.html の I18N は最新です")
            return 0
        print(
            "diff: index.html の I18N が i18n.py と一致しません。再生成してください",
            file=sys.stderr,
        )
        return 1

    new_html = _PATTERN.sub(lambda m: generated, html, count=1)
    INDEX.write_text(new_html, encoding="utf-8")
    print(f"OK: {len(STRINGS['ja'])} keys x {len(STRINGS)} langs -> preview/index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
