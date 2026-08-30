from __future__ import annotations

import subprocess
from pathlib import Path

from kaito.unzip import extract_all


def test_unicode_zipcrypto_password_roundtrip_is_strict(tmp_path: Path) -> None:
    """Japanese ZipCrypto passwords must round-trip through the DLL read path."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "f.txt").write_text("unicode pw", encoding="utf-8")
    archive = tmp_path / "unicode-password.zip"
    password = "パスワード"

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

    destination = tmp_path / "out"
    extract_all(archive, destination, password=password)
    assert (destination / "f.txt").read_text(encoding="utf-8") == "unicode pw"
