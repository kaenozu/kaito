from __future__ import annotations

import hashlib
import importlib.util
import json
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, cast

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPOSITORY_ROOT / "tools" / "generate_sbom.py"
SPEC = importlib.util.spec_from_file_location("kaito_generate_sbom", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load SBOM generator from {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

BuildSbom = Callable[..., dict[str, Any]]
WriteSbom = Callable[[dict[str, Any], Path], None]
BundledBackendComponent = Callable[[Path], dict[str, Any]]
build_sbom = cast(BuildSbom, cast(ModuleType, MODULE).build_sbom)
write_sbom = cast(WriteSbom, cast(ModuleType, MODULE).write_sbom)
bundled_backend_component = cast(
    BundledBackendComponent,
    cast(ModuleType, MODULE)._bundled_backend_component,
)


def test_sbom_contains_runtime_dependencies_and_bundled_backend() -> None:
    sbom = build_sbom(
        REPOSITORY_ROOT,
        commit="0123456789abcdef",
        generated_at=datetime(2026, 7, 13, 0, 0, tzinfo=UTC),
    )

    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.6"
    assert sbom["metadata"]["component"]["name"] == "kaito"
    project = tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    assert sbom["metadata"]["component"]["version"] == project["version"]

    component_names = {
        str(component["name"]).casefold() for component in sbom["components"]
    }
    assert {
        "customtkinter",
        "pillow",
        "platformdirs",
        "tkinterdnd2",
        "7-zip",
    } <= component_names

    root_ref = sbom["metadata"]["component"]["bom-ref"]
    root_dependencies = next(
        item for item in sbom["dependencies"] if item["ref"] == root_ref
    )
    assert "pkg:generic/7-Zip@26.02" in root_dependencies["dependsOn"]


def test_write_sbom_produces_valid_json_without_repository_paths(
    tmp_path: Path,
) -> None:
    sbom = build_sbom(
        REPOSITORY_ROOT,
        commit="fedcba9876543210",
        generated_at=datetime(2026, 7, 13, 0, 0, tzinfo=UTC),
    )
    output = tmp_path / "kaito-sbom.cdx.json"
    write_sbom(sbom, output)

    loaded = json.loads(output.read_text(encoding="utf-8"))
    serialized = json.dumps(loaded, ensure_ascii=False)
    assert loaded["metadata"]["component"]["name"] == "kaito"
    assert str(REPOSITORY_ROOT) not in serialized


def test_bundled_backend_rejects_malformed_checksum_line(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "SHA256SUMS").write_text("not-a-checksum\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Invalid bundled checksum line"):
        bundled_backend_component(tmp_path)


def test_bundled_backend_rejects_duplicate_checksum_entry(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    payload = b"bundled payload"
    (bundled / "7z.exe").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (bundled / "SHA256SUMS").write_text(
        f"{digest}  7z.exe\n{digest}  7z.exe\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="Duplicate bundled checksum entry"):
        bundled_backend_component(tmp_path)


def test_bundled_backend_rejects_checksum_mismatch(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "7z.exe").write_bytes(b"bundled payload")
    (bundled / "SHA256SUMS").write_text(
        f"{'0' * 64}  7z.exe\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="Bundled file checksum mismatch"):
        bundled_backend_component(tmp_path)
