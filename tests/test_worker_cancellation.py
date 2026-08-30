from __future__ import annotations

import threading
from pathlib import Path

import pytest

from kaito import unzip
from kaito.domain.errors import CancelledError
from kaito.worker import ExtractWorker


def test_cancel_reaches_active_archive_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "active.zip"
    archive.write_bytes(b"fixture")
    started = threading.Event()
    observed_cancel_events: list[threading.Event] = []
    result_holder = []

    monkeypatch.setattr(unzip, "list_archive", lambda path: ([], False))

    def blocked_extract(
        path: Path,
        dest: Path,
        password: str | None = None,
        on_progress=None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        assert cancel_event is not None
        observed_cancel_events.append(cancel_event)
        started.set()
        assert cancel_event.wait(timeout=2), "active extraction did not receive cancel"
        raise CancelledError(str(path))

    monkeypatch.setattr(unzip, "extract_archive", blocked_extract)

    worker = ExtractWorker(paths=[archive], dest=tmp_path / "out")
    thread = threading.Thread(target=lambda: result_holder.append(worker.run()))
    thread.start()

    assert started.wait(timeout=2)
    worker.cancel()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert observed_cancel_events == [worker.cancel_event]
    assert len(result_holder) == 1
    result = result_holder[0]
    assert result.canceled is True
    assert result.success_count == 0
    assert result.errors == []
