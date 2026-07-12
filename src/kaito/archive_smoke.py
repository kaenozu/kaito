"""配布物自身で主要アーカイブ操作を検証するスモーク診断。"""

from __future__ import annotations

import hashlib
import tempfile
import zipfile
from pathlib import Path
from typing import Callable

from kaito.archive.service import ArchiveService
from kaito.archive.sevenzip_backend import SevenZipBackend
from kaito.domain.errors import (
    InvalidPasswordError,
    PasswordRequiredError,
    UnsafeArchiveError,
)
from kaito.domain.models import CompressionOptions, ExtractionOptions

_SMOKE_PASSWORD = "Kaito-Smoke-Only-2026!"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_entry(service: ArchiveService, archive: Path, suffix: str) -> str:
    info = service.list_archive(archive)
    matches = [entry.name for entry in info.entries if entry.name.endswith(suffix)]
    if len(matches) != 1:
        raise AssertionError(
            f"expected one entry ending with {suffix!r}, found {len(matches)}"
        )
    return matches[0]


def _assert_password_failures(service: ArchiveService, archive: Path, root: Path) -> None:
    try:
        service.extract(archive, ExtractionOptions(dest_dir=root / "missing-password"))
    except PasswordRequiredError:
        pass
    else:
        raise AssertionError("missing password was not rejected")

    try:
        service.extract(
            archive,
            ExtractionOptions(
                dest_dir=root / "wrong-password",
                password="definitely-wrong",
            ),
        )
    except InvalidPasswordError:
        pass
    else:
        raise AssertionError("wrong password was not rejected")


def _redact(text: str) -> str:
    return text.replace(_SMOKE_PASSWORD, "***")


def run_archive_smoke() -> dict[str, object]:
    """主要形式を実際に作成・一覧・展開し、JSON化可能な結果を返す。"""
    checks: list[dict[str, str]] = []

    def run(name: str, operation: Callable[[], None]) -> None:
        try:
            operation()
        except Exception as exc:  # noqa: BLE001 - diagnostic must report all checks
            checks.append(
                {
                    "name": name,
                    "status": "fail",
                    "detail": _redact(f"{type(exc).__name__}: {exc}"),
                }
            )
        else:
            checks.append({"name": name, "status": "pass", "detail": "ok"})

    with tempfile.TemporaryDirectory(prefix="kaito_archive_smoke_") as temporary:
        root = Path(temporary)
        source = root / "source"
        nested = source / "日本語 と空白" / "deep"
        empty = source / "empty directory"
        nested.mkdir(parents=True)
        empty.mkdir(parents=True)
        hello = source / "hello.txt"
        japanese = nested / "日本語.txt"
        hello.write_text("kaito archive smoke\n", encoding="utf-8")
        japanese.write_text("日本語 smoke\n", encoding="utf-8")
        expected_hello_hash = _sha256(hello)

        service = ArchiveService()
        seven_zip = SevenZipBackend()

        def check_backend() -> None:
            info = seven_zip.backend_info()
            if info["version"] != "26.02" or info["integrity"] != "ok":
                raise AssertionError(f"unexpected backend info: {info}")

        run("bundled-7zip", check_backend)

        normal_zip = root / "normal.zip"

        def check_normal_zip() -> None:
            service.create(
                CompressionOptions(sources=[source], output_path=normal_zip)
            )
            entry = _find_entry(service, normal_zip, "hello.txt")
            preview = service.read_entry(normal_zip, entry)
            if preview != b"kaito archive smoke\n":
                raise AssertionError("ZIP preview mismatch")
            destination = root / "normal-zip-output"
            service.extract(normal_zip, ExtractionOptions(dest_dir=destination))
            extracted = next(destination.rglob("hello.txt"))
            if _sha256(extracted) != expected_hello_hash:
                raise AssertionError("ZIP extraction hash mismatch")

        run("zip-create-list-preview-extract", check_normal_zip)

        normal_7z = root / "normal.7z"

        def check_normal_7z() -> None:
            service.create(
                CompressionOptions(sources=[source], output_path=normal_7z)
            )
            entry = _find_entry(service, normal_7z, "hello.txt")
            preview = service.read_entry(normal_7z, entry)
            if preview != b"kaito archive smoke\n":
                raise AssertionError("7z preview mismatch")
            destination = root / "normal-7z-output"
            service.extract(normal_7z, ExtractionOptions(dest_dir=destination))
            extracted = next(destination.rglob("hello.txt"))
            if _sha256(extracted) != expected_hello_hash:
                raise AssertionError("7z extraction hash mismatch")

        run("7z-create-list-preview-extract", check_normal_7z)

        aes_zip = root / "encrypted-aes.zip"

        def check_aes_zip() -> None:
            result = seven_zip._run_7z(
                [
                    "a",
                    "-tzip",
                    "-mem=AES256",
                    str(aes_zip),
                    str(source / "*"),
                ],
                password=_SMOKE_PASSWORD,
                timeout=60,
            )
            if result.returncode != 0:
                raise AssertionError(
                    f"AES ZIP creation failed: {result.stderr or result.stdout}"
                )
            info = service.list_archive(aes_zip)
            if not info.is_encrypted:
                raise AssertionError("AES ZIP was not detected as encrypted")
            _assert_password_failures(service, aes_zip, root / "aes-errors")
            destination = root / "aes-output"
            service.extract(
                aes_zip,
                ExtractionOptions(dest_dir=destination, password=_SMOKE_PASSWORD),
            )
            extracted = next(destination.rglob("hello.txt"))
            if _sha256(extracted) != expected_hello_hash:
                raise AssertionError("AES ZIP extraction hash mismatch")
            entry = _find_entry(service, aes_zip, "hello.txt")
            if service.read_entry(aes_zip, entry, password=_SMOKE_PASSWORD) != (
                b"kaito archive smoke\n"
            ):
                raise AssertionError("AES ZIP preview mismatch")

        run("aes-zip-password-and-extract", check_aes_zip)

        encrypted_7z = root / "encrypted.7z"

        def check_encrypted_7z() -> None:
            service.create(
                CompressionOptions(
                    sources=[source],
                    output_path=encrypted_7z,
                    password=_SMOKE_PASSWORD,
                )
            )
            _assert_password_failures(service, encrypted_7z, root / "7z-errors")
            destination = root / "encrypted-7z-output"
            service.extract(
                encrypted_7z,
                ExtractionOptions(dest_dir=destination, password=_SMOKE_PASSWORD),
            )
            extracted = next(destination.rglob("hello.txt"))
            if _sha256(extracted) != expected_hello_hash:
                raise AssertionError("encrypted 7z extraction hash mismatch")

        run("encrypted-7z-password-and-extract", check_encrypted_7z)

        unsafe_zip = root / "unsafe.zip"

        def check_unsafe_rejection() -> None:
            with zipfile.ZipFile(unsafe_zip, "w") as archive:
                archive.writestr("../escape.txt", "must not escape")
            destination = root / "unsafe-output"
            try:
                service.extract(unsafe_zip, ExtractionOptions(dest_dir=destination))
            except UnsafeArchiveError:
                pass
            else:
                raise AssertionError("unsafe ZIP was not rejected")
            if (root / "escape.txt").exists():
                raise AssertionError("unsafe ZIP wrote outside destination")

        run("unsafe-path-rejection", check_unsafe_rejection)

    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "passed": len(checks) - failed,
        "failed": failed,
        "checks": checks,
    }
