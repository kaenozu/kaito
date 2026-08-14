"""AES暗号化ZIPを同梱7-Zipへルーティングする回帰テスト。

フィクスチャ (AES-256 ZIP) は tests/fixtures/archive/aes-acceptance.zip.uu の
固定バイナリで、テスト実行時に 7z.exe を起動しない。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kaito.archive.service import ArchiveService
from kaito.domain.errors import InvalidPasswordError, PasswordRequiredError
from kaito.domain.models import ExtractionOptions

_PASSWORD = "Kaito-Acceptance-2026!"
_CONTENT = b"AES ZIP secret\n"


def test_aes_zip_requires_password_and_extracts_with_correct_password(
    aes_acceptance_zip: Path,
    tmp_path: Path,
) -> None:
    service = ArchiveService()

    info = service.list_archive(aes_acceptance_zip)
    assert info.is_encrypted is True
    assert [entry.name for entry in info.entries] == ["secret.txt"]

    with pytest.raises(PasswordRequiredError):
        service.extract(
            aes_acceptance_zip,
            ExtractionOptions(dest_dir=tmp_path / "missing-password"),
        )

    with pytest.raises(InvalidPasswordError):
        service.extract(
            aes_acceptance_zip,
            ExtractionOptions(
                dest_dir=tmp_path / "wrong-password",
                password="definitely-wrong",
            ),
        )

    destination = tmp_path / "correct-password"
    service.extract(
        aes_acceptance_zip,
        ExtractionOptions(dest_dir=destination, password=_PASSWORD),
    )
    assert (destination / "secret.txt").read_bytes() == _CONTENT


def test_aes_zip_preview_uses_bundled_sevenzip(aes_acceptance_zip: Path) -> None:
    service = ArchiveService()

    assert (
        service.read_entry(aes_acceptance_zip, "secret.txt", password=_PASSWORD)
        == _CONTENT
    )
    assert (
        service.read_entry(aes_acceptance_zip, "secret.txt", password="wrong") is None
    )
