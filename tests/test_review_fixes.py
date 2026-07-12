"""PRレビューで指摘されたWindows互換性とキャンセル処理の回帰テスト。"""

from __future__ import annotations

import subprocess
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import kaito.archive.sevenzip_backend as sevenzip_backend
from kaito.archive.service import ArchiveService
from kaito.archive.sevenzip_backend import SevenZipBackend
from kaito.domain.errors import CancelledError
from kaito.domain.models import CompressionOptions, ExtractionOptions


def test_service_shares_cancel_event_with_both_backends() -> None:
    cancel_event = threading.Event()

    service = ArchiveService(cancel_event=cancel_event)

    assert service._zip_backend._cancel_event is cancel_event
    assert service._sevenzip_backend._cancel_event is cancel_event


def test_sevenzip_missing_timestamp_uses_platform_independent_epoch() -> None:
    entry = SevenZipBackend()._entry_from_slt(
        {
            "Path": "missing-time.txt",
            "Size": "0",
            "Packed Size": "0",
            "Folder": "-",
            "Encrypted": "-",
        }
    )

    assert entry is not None
    assert entry.modified == datetime(1970, 1, 1)


class _FakeProcess:
    pid = 1234

    def __init__(self) -> None:
        self.terminated = False

    def poll(self) -> int | None:
        return 0 if self.terminated else None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float) -> int:
        del timeout
        return 0

    def kill(self) -> None:
        self.terminated = True


def test_taskkill_suppresses_console_window(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []
    no_window = 0x08000000

    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr(sevenzip_backend, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        sevenzip_backend.subprocess,
        "CREATE_NO_WINDOW",
        no_window,
        raising=False,
    )
    monkeypatch.setattr(sevenzip_backend.subprocess, "run", fake_run)

    process = _FakeProcess()
    SevenZipBackend()._terminate_process(process)  # type: ignore[arg-type]

    assert calls
    assert calls[0][0][:2] == ["taskkill", "/PID"]
    assert calls[0][1]["creationflags"] == no_window


def test_zip_extraction_cancel_discards_staging_output(tmp_path: Path) -> None:
    archive_path = tmp_path / "input.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("first.txt", "first")
        archive.writestr("second.txt", "second")

    cancel_event = threading.Event()
    destination = tmp_path / "output"

    def cancel_after_first(current: int, total: int, name: str) -> None:
        del total, name
        if current == 1:
            cancel_event.set()

    service = ArchiveService(cancel_event=cancel_event)

    with pytest.raises(CancelledError):
        service.extract(
            archive_path,
            ExtractionOptions(
                dest_dir=destination,
                on_progress=cancel_after_first,
            ),
        )

    assert not destination.exists()


def test_zip_compression_cancel_removes_partial_archive(tmp_path: Path) -> None:
    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    first.write_bytes(b"a" * (2 * 1024 * 1024))
    second.write_bytes(b"b" * (2 * 1024 * 1024))
    output = tmp_path / "cancelled.zip"
    cancel_event = threading.Event()

    def cancel_after_first(current: int, total: int, name: str) -> None:
        del total, name
        if current == 1:
            cancel_event.set()

    service = ArchiveService(cancel_event=cancel_event)

    with pytest.raises(CancelledError):
        service.create(
            CompressionOptions(
                sources=[first, second],
                output_path=output,
                on_progress=cancel_after_first,
            )
        )

    assert not output.exists()
    assert not list(tmp_path.glob(".cancelled.*.tmp.zip"))
