"""エントリポイントの安全ガード。"""

from __future__ import annotations

from pathlib import Path

from kaito.__main__ import _existing_context_compression_output


def test_context_compression_allows_missing_output(tmp_path: Path) -> None:
    source = tmp_path / "report.txt"
    source.write_text("data", encoding="utf-8")

    assert _existing_context_compression_output(["--compress", str(source)]) is None


def test_context_compression_detects_existing_default_output(tmp_path: Path) -> None:
    source = tmp_path / "report.txt"
    source.write_text("data", encoding="utf-8")
    output = tmp_path / "report.zip"
    output.write_bytes(b"existing")

    assert _existing_context_compression_output(["--compress", str(source)]) == output
    assert output.read_bytes() == b"existing"


def test_context_compression_detects_source_zip_as_own_output(tmp_path: Path) -> None:
    source = tmp_path / "archive.zip"
    source.write_bytes(b"existing archive")

    assert _existing_context_compression_output(["--compress", str(source)]) == source


def test_non_context_arguments_are_ignored(tmp_path: Path) -> None:
    source = tmp_path / "report.txt"
    source.write_text("data", encoding="utf-8")
    (tmp_path / "report.zip").write_bytes(b"existing")

    assert _existing_context_compression_output([str(source)]) is None
    assert _existing_context_compression_output(["--self-test"]) is None
