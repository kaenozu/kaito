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


def _run_7z(args: list[str]) -> None:
    result = subprocess.run(
        [str(_SEVENZ), *args, "-y"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
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
            f"RAR fixture hash mismatch: {source.name}: {digest} != {expected_sha256}"
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


@pytest.fixture
def sevenz_available() -> bool:
    return _SEVENZ.is_file()


@pytest.fixture
def normal_7z(tmp_dir: Path, sevenz_available: bool) -> Path:
    if not sevenz_available:
        pytest.skip("bundled 7-Zip not available")
    source = tmp_dir / "7zsrc"
    source.mkdir()
    (source / "hello.txt").write_text("Hello World", encoding="utf-8")
    sub = source / "sub"
    sub.mkdir()
    (sub / "file.txt").write_text("Nested file", encoding="utf-8")
    path = tmp_dir / "test.7z"
    _run_7z(["a", str(path), str(source / "*")])
    return path


@pytest.fixture
def encrypted_7z(tmp_dir: Path, sevenz_available: bool) -> Path:
    if not sevenz_available:
        pytest.skip("bundled 7-Zip not available")
    source = tmp_dir / "encsrc"
    source.mkdir()
    (source / "secret.txt").write_text("Secret Data", encoding="utf-8")
    path = tmp_dir / "encrypted.7z"
    _run_7z(["a", "-psecret123", str(path), str(source / "*")])
    return path


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
def japanese_7z(tmp_dir: Path, sevenz_available: bool) -> Path:
    if not sevenz_available:
        pytest.skip("bundled 7-Zip not available")
    source = tmp_dir / "jp_src"
    source.mkdir()
    (source / "日本語.txt").write_text("Japanese filename test", encoding="utf-8")
    path = tmp_dir / "japanese.7z"
    _run_7z(["a", str(path), str(source / "*")])
    return path


@pytest.fixture
def corrupt_zip(tmp_dir: Path) -> Path:
    path = tmp_dir / "corrupt.zip"
    path.write_bytes(b"not a zip file at all\x00\x01\x02")
    return path


@pytest.fixture
def corrupt_7z(tmp_dir: Path, sevenz_available: bool) -> Path:
    if not sevenz_available:
        pytest.skip("bundled 7-Zip not available")
    path = tmp_dir / "corrupt.7z"
    path.write_bytes(b"\x00" * 100)
    return path


@pytest.fixture
def corrupt_rar(tmp_dir: Path, sevenz_available: bool) -> Path:
    if not sevenz_available:
        pytest.skip("bundled 7-Zip not available")
    path = tmp_dir / "corrupt.rar"
    path.write_bytes(b"Rar!\x00" + b"\x00" * 100)
    return path
