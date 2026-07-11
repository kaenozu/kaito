"""7-Zipプロセス管理と配布物分離のテスト。"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from kaito.archive.sevenzip_backend import SevenZipBackend, redact_command
from kaito.domain.errors import CancelledError, ExternalToolNotFoundError


def test_backend_info_uses_verified_bundled_copy() -> None:
    info = SevenZipBackend().backend_info()
    assert info["available"] is True
    assert info["source"] == "bundled"
    assert info["version"] == "26.02"
    assert info["integrity"] == "ok"
    assert info["sha256"] == info["expected_sha256"]
    assert Path(info["path"]).name.lower() == "7z.exe"


def test_frozen_mode_never_falls_back_to_system(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    backend = SevenZipBackend()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("KAITO_ALLOW_SYSTEM_7Z", "1")
    monkeypatch.setenv("KAITO_7Z_PATH", "C:/Program Files/7-Zip/7z.exe")

    with pytest.raises(ExternalToolNotFoundError, match="同梱7-Zip"):
        backend._find_tool()


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (["7z", "x", "a.7z", "-psecret"], ["7z", "x", "a.7z", "-p***"]),
        (["7z", "x", "-p", "secret", "a.7z"], ["7z", "x", "-p", "***", "a.7z"]),
        (
            ["7z", "x", "--password=secret", "a.7z"],
            ["7z", "x", "--password=***", "a.7z"],
        ),
    ],
)
def test_redact_command_removes_secrets(
    command: list[str], expected: list[str]
) -> None:
    assert redact_command(command) == expected
    assert "secret" not in " ".join(redact_command(command))


def test_actual_7z_result_does_not_expose_password(encrypted_7z: Path) -> None:
    secret = "KAITO_TEST_SECRET_DO_NOT_LOG_9f6c2a"
    result = SevenZipBackend()._run_7z(
        ["t", str(encrypted_7z)], password=secret, timeout=30
    )
    rendered = "\n".join(
        [" ".join(str(arg) for arg in result.args), result.stdout, result.stderr]
    )
    assert secret not in rendered
    assert "-p***" in " ".join(str(arg) for arg in result.args)


def test_running_7z_process_is_terminated_on_cancel() -> None:
    cancel_event = threading.Event()
    backend = SevenZipBackend(cancel_event=cancel_event)
    captured: list[BaseException] = []

    def run_benchmark() -> None:
        try:
            backend._run_7z(["b", "-mmt=1"], timeout=60)
        except BaseException as exc:  # noqa: BLE001 - thread result is asserted below
            captured.append(exc)

    worker = threading.Thread(target=run_benchmark, daemon=True)
    worker.start()

    deadline = time.monotonic() + 10
    process = None
    while time.monotonic() < deadline:
        process = backend._current_process
        if process is not None and process.poll() is None:
            break
        time.sleep(0.05)

    assert process is not None, "7-Zip process did not start"
    assert process.poll() is None
    pid = process.pid

    cancel_event.set()
    worker.join(timeout=15)

    assert not worker.is_alive(), f"cancelled 7-Zip process {pid} did not stop"
    assert process.poll() is not None
    assert len(captured) == 1
    assert isinstance(captured[0], CancelledError)
    assert backend._current_process is None
