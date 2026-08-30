from __future__ import annotations

import subprocess
from pathlib import Path

from kaito.unzip import extract_all


def test_ascii_zipcrypto_password_roundtrip_is_strict(tmp_path: Path) -> None:
    """The documented ASCII-only ZipCrypto password boundary must work."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "f.txt").write_text("zipcrypto pw", encoding="utf-8")
    archive = tmp_path / "ascii-password.zip"
    password = "Kaito-ASCII-2026"

    repo_root = Path(__file__).resolve().parents[1]
    seven_zip = repo_root / "bundled" / "7z.exe"
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        [
            str(seven_zip),
            "a",
            "-tzip",
            "-mem=ZipCrypto",
            f"-p{password}",
            str(archive),
            str(source / "f.txt"),
            "-y",
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

    destination = tmp_path / "out"
    extract_all(archive, destination, password=password)
    assert (destination / "f.txt").read_text(encoding="utf-8") == "zipcrypto pw"


def test_zipcrypto_password_limitation_is_explicitly_documented() -> None:
    documentation = Path("docs/PASSWORD_SUPPORT.md").read_text(encoding="utf-8")
    assert "ZipCrypto" in documentation
    assert "ASCII" in documentation
    assert "AES-256" in documentation
    assert "non-ASCII" in documentation
