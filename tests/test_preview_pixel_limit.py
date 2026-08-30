from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from kaito.archive.service import ArchiveService
from kaito.domain.errors import UnsafeArchiveError
from kaito.domain.models import SafetyLimits


def _png_bytes(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color="white").save(buffer, format="PNG")
    return buffer.getvalue()


def _service_with_entry(
    monkeypatch: pytest.MonkeyPatch, *, data: bytes, pixel_limit: int
) -> ArchiveService:
    service = ArchiveService(
        safety_limits=SafetyLimits(preview_max_image_pixels=pixel_limit)
    )
    monkeypatch.setattr(
        service._dll_backend,  # noqa: SLF001 - backend is isolated for service test
        "check_tool_availability",
        lambda: (True, None),
    )
    monkeypatch.setattr(
        service._dll_backend,  # noqa: SLF001 - backend is isolated for service test
        "read_entry",
        lambda path, entry_name, password=None: data,
    )
    return service


def test_read_entry_rejects_image_over_configured_pixel_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service_with_entry(
        monkeypatch,
        data=_png_bytes(101, 100),
        pixel_limit=10_000,
    )

    with pytest.raises(UnsafeArchiveError, match="101x100=10100 > 10000"):
        service.read_entry(Path("sample.zip"), "preview.png")


def test_read_entry_allows_image_at_configured_pixel_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _png_bytes(100, 100)
    service = _service_with_entry(monkeypatch, data=data, pixel_limit=10_000)

    assert service.read_entry(Path("sample.zip"), "preview.png") == data


def test_non_image_preview_is_not_subject_to_pixel_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = b"plain text"
    service = _service_with_entry(monkeypatch, data=data, pixel_limit=1)

    assert service.read_entry(Path("sample.zip"), "notes.txt") == data
