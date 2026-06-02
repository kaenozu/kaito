"""
tests/conftest.py
テスト用の共通フィクスチャ
"""

import tempfile
import zipfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_dir() -> Path:
    """テスト用一時ディレクトリ"""
    d = Path(tempfile.mkdtemp())
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def normal_zip(tmp_dir: Path) -> Path:
    """通常のZIPファイルを作成"""
    path = tmp_dir / "test.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("hello.txt", "Hello World")
        zf.writestr("sub/file.txt", "Nested file")
        zf.writestr("sub/deep/secret.md", "# Secret")
    return path


@pytest.fixture
def zip_with_dir_entries(tmp_dir: Path) -> Path:
    """ディレクトリエントリを含むZIP"""
    path = tmp_dir / "dirs.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("folder/", "")
        zf.writestr("folder/a.txt", "A")
        zf.writestr("empty_dir/", "")
    return path


@pytest.fixture
def empty_zip(tmp_dir: Path) -> Path:
    """空のZIPファイル"""
    path = tmp_dir / "empty.zip"
    with zipfile.ZipFile(path, "w"):
        pass
    return path
