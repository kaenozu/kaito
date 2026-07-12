"""Generate deterministic Windows acceptance-test data.

This helper is invoked by ``tools/prepare_acceptance.ps1``. It only writes
inside the explicitly supplied work directory.
"""

from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import os
import struct
import zipfile
import zlib
from pathlib import Path

_RAR_FIXTURES = {
    "normal.rar": (
        "test_read_format_rar_subblock.rar.uu",
        "e871277670529329cc2c06f178ced453c560d03fd26c76614f42ef9c06b50af0",
    ),
    "encrypted.rar": (
        "test_read_format_rar_encryption_data.rar.uu",
        "84ba9afcf0673aab0d1421d931e76a19294b12117483879c4b58598d3d71e83e",
    ),
    "link-entry.rar": (
        "test_read_format_rar.rar.uu",
        "d421b86f6290aefad61b2a36737253b2b30fe27c156bd95abfc230f24fe0307e",
    ),
}


def _decode_uu(source: Path, destination: Path, expected_sha256: str) -> None:
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
            f"RAR fixture hash mismatch: {source.name}: "
            f"{digest} != {expected_sha256}"
        )
    destination.write_bytes(output)


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def _write_png(path: Path, width: int = 128, height: int = 128) -> None:
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend(
                (
                    x * 255 // (width - 1),
                    y * 255 // (height - 1),
                    128,
                )
            )

    payload = b"\x89PNG\r\n\x1a\n"
    payload += _png_chunk(
        b"IHDR",
        struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0),
    )
    payload += _png_chunk(b"IDAT", zlib.compress(bytes(raw), level=9))
    payload += _png_chunk(b"IEND", b"")
    path.write_bytes(payload)


def _write_random_file(path: Path, size_mib: int) -> None:
    chunk_size = 1024 * 1024
    with path.open("wb") as stream:
        for _ in range(size_mib):
            stream.write(os.urandom(chunk_size))


def generate(repo_root: Path, work_root: Path, large_file_size_mib: int) -> dict[str, object]:
    source_root = work_root / "source-data"
    nested = source_root / "日本語 と空白" / "深い階層" / "level-3"
    empty_directory = source_root / "empty directory"
    preview_root = source_root / "preview"
    cancel_root = work_root / "cancel-source"
    archives_root = work_root / "archives"

    for directory in (
        nested,
        empty_directory,
        preview_root,
        cancel_root,
        archives_root,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    (source_root / "hello.txt").write_text(
        "Hello from kaito acceptance test.\n",
        encoding="utf-8",
    )
    (nested / "日本語 ファイル.txt").write_text(
        "日本語、空白、階層の保持確認。\n",
        encoding="utf-8",
    )
    (nested / "emoji-😀.txt").write_text(
        "Emoji filename test.\n",
        encoding="utf-8",
    )
    (preview_root / "preview.txt").write_text(
        ("0123456789abcdef" * 1024) + "\n",
        encoding="utf-8",
    )
    _write_png(preview_root / "preview-image.png")

    with zipfile.ZipFile(archives_root / "windows-case-collision.zip", "w") as archive:
        archive.writestr("FILE.txt", "upper")
        archive.writestr("file.txt", "lower")

    with zipfile.ZipFile(archives_root / "duplicate-entry.zip", "w") as archive:
        archive.writestr("duplicate.txt", "first")
        archive.writestr("duplicate.txt", "second")

    with zipfile.ZipFile(archives_root / "unsafe-windows-names.zip", "w") as archive:
        archive.writestr("CON.txt", "reserved")
        archive.writestr("folder/data.txt:secret", "alternate data stream")

    (archives_root / "corrupt.zip").write_bytes(b"not a zip file\x00\x01\x02")
    (archives_root / "corrupt.7z").write_bytes(b"\x00" * 100)
    (archives_root / "corrupt.rar").write_bytes(b"Rar!\x00" + b"\x00" * 100)

    fixture_root = repo_root / "tests" / "fixtures" / "rar"
    for output_name, (source_name, expected_hash) in _RAR_FIXTURES.items():
        _decode_uu(
            fixture_root / source_name,
            archives_root / output_name,
            expected_hash,
        )

    large_path = cancel_root / f"random-{large_file_size_mib}-MiB.bin"
    _write_random_file(large_path, large_file_size_mib)

    result: dict[str, object] = {
        "source_root": str(source_root),
        "archives_root": str(archives_root),
        "cancel_source": str(large_path),
        "large_file_size_mib": large_file_size_mib,
        "generated_archives": sorted(path.name for path in archives_root.iterdir()),
    }
    (work_root / "python-generation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--large-file-size-mib", type=int, default=128)
    args = parser.parse_args()

    if not 1 <= args.large_file_size_mib <= 4096:
        parser.error("--large-file-size-mib must be between 1 and 4096")

    result = generate(
        args.repo_root.resolve(),
        args.work_root.resolve(),
        args.large_file_size_mib,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
