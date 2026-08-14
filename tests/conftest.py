"""テスト用の共通フィクスチャ。"""

from __future__ import annotations

import binascii
import hashlib
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SEVENZ = _REPO_ROOT / "bundled" / "7z.exe"
_RAR_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "rar"
_ARCHIVE_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "archive"


def _run_7z(args: list[str]) -> None:
    result = subprocess.run(
        [str(_SEVENZ), *args, "-y", "-sccUTF-8"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"7z failed (code={result.returncode}): {result.stderr or result.stdout}"
        )


def _decode_uu(source: Path, destination: Path, expected_sha256: str) -> Path:
    """固定済みuuencode fixtureをデコードし、出力ハッシュを検証する。"""
    lines = source.read_text(encoding="ascii").splitlines()
    if not lines or not lines[0].startswith("begin ") or lines[-1] != "end":
        raise RuntimeError(f"invalid uu fixture: {source}")
    output = bytearray()
    for line in lines[1:-1]:
        if line:
            output.extend(binascii.a2b_uu(line.encode("ascii")))
    digest = hashlib.sha256(output).hexdigest()
    if digest != expected_sha256:
        raise RuntimeError(
            f"fixture hash mismatch: {source.name}: {digest} != {expected_sha256}"
        )
    destination.write_bytes(output)
    return destination


@pytest.fixture
def tmp_dir() -> Path:
    directory = Path(tempfile.mkdtemp())
    yield directory
    shutil.rmtree(directory, ignore_errors=True)


@pytest.fixture
def normal_zip(tmp_dir: Path) -> Path:
    path = tmp_dir / "test.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("hello.txt", "Hello World")
        archive.writestr("sub/file.txt", "Nested file")
        archive.writestr("sub/deep/secret.md", "# Secret")
    return path


@pytest.fixture
def zip_with_dir_entries(tmp_dir: Path) -> Path:
    path = tmp_dir / "dirs.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("folder/", "")
        archive.writestr("folder/a.txt", "A")
        archive.writestr("empty_dir/", "")
    return path


@pytest.fixture
def empty_zip(tmp_dir: Path) -> Path:
    path = tmp_dir / "empty.zip"
    with zipfile.ZipFile(path, "w"):
        pass
    return path


# 7z / 暗号化アーカイブは固定 (uuencode) バイナリからデコードする。
# 不足するフィクスチャの生成のみ bundled/7z.exe を起動し、その際は
# CREATE_NO_WINDOW でコンソール窓を出さない。読み取り系は 7z.dll に統一され
# subprocess を生まない (src/kaito/archive/dll_backend.py)。


@pytest.fixture
def normal_7z(tmp_dir: Path) -> Path:
    return _decode_uu(
        _ARCHIVE_FIXTURES / "normal.7z.uu",
        tmp_dir / "normal.7z",
        "b6a158526223e792ad0f22addb8d504cb7acc974b46274edcbfdd5df97151187",
    )


@pytest.fixture
def encrypted_7z(tmp_dir: Path) -> Path:
    return _decode_uu(
        _ARCHIVE_FIXTURES / "encrypted.7z.uu",
        tmp_dir / "encrypted.7z",
        "513c3f6769c637562ac20e4778b9c7ab2c699fc922f0dede7e0b107a162fb026",
    )


@pytest.fixture
def japanese_7z(tmp_dir: Path) -> Path:
    return _decode_uu(
        _ARCHIVE_FIXTURES / "japanese.7z.uu",
        tmp_dir / "japanese.7z",
        "eb6c83d52cf42527f84c4c639aab33a3b17bc679501045584d7b808e6dad0afb",
    )


@pytest.fixture
def dll_encrypted_aes_zip(tmp_dir: Path) -> Path:
    return _decode_uu(
        _ARCHIVE_FIXTURES / "dll-encrypted-aes.zip.uu",
        tmp_dir / "dll-encrypted-aes.zip",
        "1cc6e013574a650cd8b6feb4dc9c7fb8562bb122ea6c717503ae83f4224e17b3",
    )


@pytest.fixture
def dll_encrypted_7z(tmp_dir: Path) -> Path:
    return _decode_uu(
        _ARCHIVE_FIXTURES / "dll-encrypted.7z.uu",
        tmp_dir / "dll-encrypted.7z",
        "f201db1aa1c45855f20674be72ea7afab74f0ca0b30575584dea6917c004ef6d",
    )


@pytest.fixture
def dll_enc_headers_7z(tmp_dir: Path) -> Path:
    return _decode_uu(
        _ARCHIVE_FIXTURES / "dll-enc-headers.7z.uu",
        tmp_dir / "dll-enc-headers.7z",
        "1be2edb04e9adeb797bebcfb99d307669aa5347801f1492bac4af7cca8478f29",
    )


@pytest.fixture
def aes_acceptance_zip(tmp_dir: Path) -> Path:
    return _decode_uu(
        _ARCHIVE_FIXTURES / "aes-acceptance.zip.uu",
        tmp_dir / "aes-acceptance.zip",
        "c5721e02ce5d9f5fb867a0a1fceedfca156553d85857fc0ae5aff404f38da176",
    )


@pytest.fixture
def normal_rar(tmp_dir: Path) -> Path:
    return _decode_uu(
        _RAR_FIXTURES / "test_read_format_rar_subblock.rar.uu",
        tmp_dir / "normal.rar",
        "e871277670529329cc2c06f178ced453c560d03fd26c76614f42ef9c06b50af0",
    )


@pytest.fixture
def encrypted_rar(tmp_dir: Path) -> Path:
    return _decode_uu(
        _RAR_FIXTURES / "test_read_format_rar_encryption_data.rar.uu",
        tmp_dir / "encrypted.rar",
        "84ba9afcf0673aab0d1421d931e76a19294b12117483879c4b58598d3d71e83e",
    )


@pytest.fixture
def symlink_rar(tmp_dir: Path) -> Path:
    return _decode_uu(
        _RAR_FIXTURES / "test_read_format_rar.rar.uu",
        tmp_dir / "symlink.rar",
        "d421b86f6290aefad61b2a36737253b2b30fe27c156bd95abfc230f24fe0307e",
    )


@pytest.fixture
def corrupt_zip(tmp_dir: Path) -> Path:
    path = tmp_dir / "corrupt.zip"
    path.write_bytes(b"not a zip file at all\x00\x01\x02")
    return path


@pytest.fixture
def corrupt_7z(tmp_dir: Path) -> Path:
    path = tmp_dir / "corrupt.7z"
    path.write_bytes(b"\x00" * 100)
    return path


@pytest.fixture
def corrupt_rar(tmp_dir: Path) -> Path:
    path = tmp_dir / "corrupt.rar"
    path.write_bytes(b"Rar!\x00" + b"\x00" * 100)
    return path
