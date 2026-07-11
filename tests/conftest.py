"""
tests/conftest.py
テスト用の共通フィクスチャ（実アーカイブファイルを含む）
"""

import subprocess
import tempfile
import zipfile
from pathlib import Path

import pytest

_SEVENZ = Path("C:/Program Files/7-Zip/7z.exe")


def _run_7z(args: list[str]) -> None:
    """Run 7z and raise if non-zero exit."""
    r = subprocess.run(
        [str(_SEVENZ), *args, "-y"], capture_output=True, text=True, timeout=30
    )
    if r.returncode != 0:
        raise RuntimeError(f"7z failed (code={r.returncode}): {r.stderr}")


# ---- ZIP fixtures ----


@pytest.fixture
def tmp_dir() -> Path:
    d = Path(tempfile.mkdtemp())
    yield d
    import shutil

    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def normal_zip(tmp_dir: Path) -> Path:
    path = tmp_dir / "test.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("hello.txt", "Hello World")
        zf.writestr("sub/file.txt", "Nested file")
        zf.writestr("sub/deep/secret.md", "# Secret")
    return path


@pytest.fixture
def zip_with_dir_entries(tmp_dir: Path) -> Path:
    path = tmp_dir / "dirs.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("folder/", "")
        zf.writestr("folder/a.txt", "A")
        zf.writestr("empty_dir/", "")
    return path


@pytest.fixture
def empty_zip(tmp_dir: Path) -> Path:
    path = tmp_dir / "empty.zip"
    with zipfile.ZipFile(path, "w"):
        pass
    return path


# ---- 7z fixtures (require 7-Zip installed) ----


@pytest.fixture
def sevenz_available() -> bool:
    return _SEVENZ.exists()


@pytest.fixture
def normal_7z(tmp_dir: Path, sevenz_available: bool) -> Path:
    if not sevenz_available:
        pytest.skip("7-Zip not available")
    src = tmp_dir / "7zsrc"
    src.mkdir()
    (src / "hello.txt").write_text("Hello World")
    sub_src = src / "sub"
    sub_src.mkdir()
    (sub_src / "file.txt").write_text("Nested file")

    path = tmp_dir / "test.7z"
    _run_7z(["a", str(path), str(src / "*")])
    return path


@pytest.fixture
def encrypted_7z(tmp_dir: Path, sevenz_available: bool) -> Path:
    if not sevenz_available:
        pytest.skip("7-Zip not available")
    src = tmp_dir / "encsrc"
    src.mkdir()
    (src / "secret.txt").write_text("Secret Data")
    path = tmp_dir / "encrypted.7z"
    _run_7z(["a", "-psecret123", str(path), str(src / "*")])
    return path


@pytest.fixture
def normal_rar(tmp_dir: Path) -> Path:
    """RAR fixture placeholder.

    7-Zip can only extract RAR, not create it.
    Without WinRAR or a RAR creation tool, valid RAR test fixtures
    cannot be generated programmatically. This fixture provides a
    .rar file for format detection and error handling tests only.

    For actual RAR extraction E2E, you need WinRAR to create the file,
    then place it in tests/fixtures/ with SHA-256 verification.
    """
    path = tmp_dir / "test.rar"
    path.write_bytes(b"Rar!\x1a\x07\x00" + b"\x00" * 50)
    return path


@pytest.fixture
def encrypted_rar(tmp_dir: Path) -> Path:
    """Encrypted RAR fixture placeholder (same limitation as normal_rar)."""
    path = tmp_dir / "encrypted.rar"
    path.write_bytes(b"Rar!\x1a\x07\x00" + b"\x00" * 50)
    return path


@pytest.fixture
def japanese_7z(tmp_dir: Path, sevenz_available: bool) -> Path:
    if not sevenz_available:
        pytest.skip("7-Zip not available")
    src = tmp_dir / "jp_src"
    src.mkdir()
    (src / "日本語.txt").write_text("Japanese filename test")
    path = tmp_dir / "japanese.7z"
    _run_7z(["a", str(path), str(src / "*")])
    return path


@pytest.fixture
def corrupt_zip(tmp_dir: Path) -> Path:
    path = tmp_dir / "corrupt.zip"
    path.write_bytes(b"not a zip file at all\x00\x01\x02")
    return path


@pytest.fixture
def corrupt_7z(tmp_dir: Path, sevenz_available: bool) -> Path:
    if not sevenz_available:
        pytest.skip("7-Zip not available")
    path = tmp_dir / "corrupt.7z"
    path.write_bytes(b"\x00" * 100)
    return path


@pytest.fixture
def corrupt_rar(tmp_dir: Path, sevenz_available: bool) -> Path:
    if not sevenz_available:
        pytest.skip("7-Zip not available")
    path = tmp_dir / "corrupt.rar"
    path.write_bytes(b"Rar!\x00" + b"\x00" * 100)
    return path
