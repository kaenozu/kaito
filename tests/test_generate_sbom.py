from __future__ import annotations

import importlib.util
import json
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPOSITORY_ROOT / "tools" / "generate_sbom.py"
SPEC = importlib.util.spec_from_file_location("kaito_generate_sbom", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load SBOM generator from {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

BuildSbom = Callable[..., dict[str, Any]]
WriteSbom = Callable[[dict[str, Any], Path], None]
build_sbom = cast(BuildSbom, cast(ModuleType, MODULE).build_sbom)
write_sbom = cast(WriteSbom, cast(ModuleType, MODULE).write_sbom)


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

    component_names = {component["name"] for component in sbom["components"]}
    assert {
        "customtkinter",
        "Pillow",
        "platformdirs",
        "tkinterdnd2",
        "7-Zip",
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
