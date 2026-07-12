"""AES暗号化ZIPを同梱7-Zipへルーティングする回帰テスト。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kaito.archive.service import ArchiveService
from kaito.domain.errors import InvalidPasswordError, PasswordRequiredError
from kaito.domain.models import ExtractionOptions

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SEVEN_ZIP = _REPO_ROOT / "bundled" / "7z.exe"
_PASSWORD = "Kaito-Acceptance-2026!"
_CONTENT = b"AES ZIP secret\n"


def _create_aes_zip(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    (source / "secret.txt").write_bytes(_CONTENT)
    archive = tmp_path / "encrypted-aes.zip"
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        [
            str(_SEVEN_ZIP),
            "a",
            "-tzip",
            "-mem=AES256",
            f"-p{_PASSWORD}",
            str(archive),
            str(source / "*"),
            "-y",
            "-sccUTF-8",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
        creationflags=creation_flags,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return archive


def test_aes_zip_requires_password_and_extracts_with_correct_password(
    tmp_path: Path,
) -> None:
    archive = _create_aes_zip(tmp_path)
    service = ArchiveService()

    info = service.list_archive(archive)
    assert info.is_encrypted is True
    assert [entry.name for entry in info.entries] == ["secret.txt"]

    with pytest.raises(PasswordRequiredError):
        service.extract(
            archive,
            ExtractionOptions(dest_dir=tmp_path / "missing-password"),
        )

    with pytest.raises(InvalidPasswordError):
        service.extract(
            archive,
            ExtractionOptions(
                dest_dir=tmp_path / "wrong-password",
                password="definitely-wrong",
            ),
        )

    destination = tmp_path / "correct-password"
    service.extract(
        archive,
        ExtractionOptions(dest_dir=destination, password=_PASSWORD),
    )
    assert (destination / "secret.txt").read_bytes() == _CONTENT


def test_aes_zip_preview_uses_bundled_sevenzip(tmp_path: Path) -> None:
    archive = _create_aes_zip(tmp_path)
    service = ArchiveService()

    assert service.read_entry(archive, "secret.txt", password=_PASSWORD) == _CONTENT
    assert service.read_entry(archive, "secret.txt", password="wrong") is None
