from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from kaito.archive.service import ArchiveService
from kaito.diagnostics import build_diagnostic_report
from kaito.domain.errors import InvalidPasswordError
from kaito.domain.models import ArchiveEntry, CompressionOptions, ExtractionOptions


def test_zip_integrity_reads_every_member(tmp_path: Path) -> None:
    archive = tmp_path / "sample.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as handle:
        handle.writestr("a.txt", "alpha")
        handle.writestr("nested/b.txt", "beta")

    result = ArchiveService().test_archive(archive)

    assert result.passed
    assert result.checked_entries == 2
    assert "CRC" in result.message


def test_encrypted_aes_zip_creation_and_extraction(tmp_path: Path) -> None:
    source = tmp_path / "secret.txt"
    source.write_text("classified", encoding="utf-8")
    archive = tmp_path / "secret.zip"
    service = ArchiveService()

    service.create(
        CompressionOptions(
            sources=[source],
            output_path=archive,
            compression_level=6,
            password="correct horse battery staple",
        )
    )

    assert archive.read_bytes().startswith(b"PK")
    info = service.list_archive(archive)
    assert info.is_encrypted

    with pytest.raises(InvalidPasswordError):
        service.extract(
            archive,
            ExtractionOptions(dest_dir=tmp_path / "wrong", password="wrong"),
        )

    destination = tmp_path / "correct"
    service.extract(
        archive,
        ExtractionOptions(
            dest_dir=destination,
            password="correct horse battery staple",
        ),
    )
    assert (destination / "secret.txt").read_text(encoding="utf-8") == "classified"
    assert service.test_archive(archive, password="correct horse battery staple").passed


def test_smart_destination_uses_numbered_container_on_collision(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "bundle.zip"
    existing = tmp_path / "bundle"
    existing.mkdir()
    entries = [
        ArchiveEntry(
            name="loose-a.txt",
            size=1,
            compressed_size=1,
            modified=datetime(2026, 1, 1),
            is_dir=False,
        ),
        ArchiveEntry(
            name="loose-b.txt",
            size=1,
            compressed_size=1,
            modified=datetime(2026, 1, 1),
            is_dir=False,
        ),
    ]

    resolved = ArchiveService.resolve_extract_dest(
        tmp_path, archive, entries, avoid_existing=True
    )

    assert resolved == tmp_path / "bundle (2)"


def _stub_backend_info(service: ArchiveService, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        service,
        "backend_info",
        lambda: {
            "available": True,
            "source": "bundled",
            "version": "26.02",
            "integrity": "ok",
            "sha256": "same",
            "expected_sha256": "same",
        },
    )


def test_diagnostic_report_excludes_paths_entries_and_passwords(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = ArchiveService()
    _stub_backend_info(service, monkeypatch)
    secret_path = tmp_path / "private" / "customer-name.zip"

    report_text = build_diagnostic_report(
        service,
        archive_path=secret_path,
        entry_count=4,
        encrypted=True,
        last_error=f"failed at {secret_path} -pSuperSecret",
    )
    report = json.loads(report_text)

    assert report["archive"] == {
        "extension": ".zip",
        "entry_count": 4,
        "encrypted": True,
    }
    assert str(tmp_path) not in report_text
    assert "customer-name" not in report_text
    assert "SuperSecret" not in report_text
    assert "-p***" in report["last_error"]


def test_diagnostic_report_redacts_quoted_password_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ArchiveService()
    _stub_backend_info(service, monkeypatch)

    report_text = build_diagnostic_report(
        service,
        last_error=(
            '7z failed -p"my secret password" '
            "--password='another secret' remaining"
        ),
    )
    report = json.loads(report_text)

    assert "my secret password" not in report_text
    assert "another secret" not in report_text
    assert "-p***" in report["last_error"]
    assert "--password=***" in report["last_error"]
    assert "remaining" in report["last_error"]
