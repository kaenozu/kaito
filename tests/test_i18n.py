"""
tests/test_i18n.py
i18n.py のテスト（言語切替と ja/en 文字列の整合性）
"""

import re

import pytest

from kaito import i18n


@pytest.fixture(autouse=True)
def _restore_language() -> None:
    """テスト前後で言語を日本語に戻す（他テストへの影響を防ぐ）"""
    i18n.set_language("ja")
    yield
    i18n.set_language("ja")


def _placeholders(text: str) -> set[str]:
    """formatプレースホルダ {xxx} の集合を返す"""
    return set(re.findall(r"\{[a-z_]+\}", text))


class TestI18n:
    def test_default_language_ja(self) -> None:
        assert i18n.get_language() == "ja"
        assert i18n.tr("app.open") == "開く"

    def test_set_language_en(self) -> None:
        i18n.set_language("en")
        assert i18n.get_language() == "en"
        assert i18n.tr("app.open") == "Open"
        assert i18n.tr("app.extract") == "Extract"
        assert i18n.tr("settings.save") == "Save"

    def test_unknown_language_falls_back_to_ja(self) -> None:
        i18n.set_language("fr")
        assert i18n.get_language() == "ja"
        assert i18n.tr("app.open") == "開く"

    def test_unknown_key_returns_key(self) -> None:
        assert i18n.tr("no.such.key") == "no.such.key"

    def test_all_keys_present_in_both_languages(self) -> None:
        """ja と en で同じキーセットを持つ（欠落があれば失敗）"""
        ja_keys = set(i18n.STRINGS["ja"])
        en_keys = set(i18n.STRINGS["en"])
        assert ja_keys == en_keys

    def test_placeholders_consistent(self) -> None:
        """formatプレースホルダが両言語で揃っている（format() 引数の不一致を防ぐ）"""
        for key, ja_text in i18n.STRINGS["ja"].items():
            assert _placeholders(ja_text) == _placeholders(i18n.STRINGS["en"][key]), key

    def test_format_placeholders_work(self) -> None:
        """代表的なメッセージが両言語で正しくフォーマットできる"""
        i18n.set_language("ja")
        assert i18n.tr("msg.extract_done").format(n=3) == "解凍完了 (3アーカイブ)"
        i18n.set_language("en")
        assert (
            i18n.tr("msg.extract_done").format(n=3)
            == "Extraction complete (3 archive(s))"
        )
        assert i18n.tr("msg.password_prompt").format(name="a.zip") == (
            "a.zip is password protected\nEnter the password:"
        )
