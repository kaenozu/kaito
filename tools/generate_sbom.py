from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import tomllib
import uuid
from collections import deque
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

CODE_NAMESPACE = uuid.UUID("2dfcc5f7-629d-4fca-900a-623546b466ea")


def _purl(name: str, version: str) -> str:
    normalized = canonicalize_name(name)
    return f"pkg:pypi/{normalized}@{version}"


def _active_requirements(distribution: metadata.Distribution) -> list[str]:
    environment = default_environment()
    environment["extra"] = ""
    names: list[str] = []
    for raw_requirement in distribution.requires or []:
        requirement = Requirement(raw_requirement)
        if requirement.marker is not None and not requirement.marker.evaluate(
            environment
        ):
            continue
        names.append(requirement.name)
    return names


def _license_entry(distribution: metadata.Distribution) -> list[dict[str, Any]] | None:
    expression = distribution.metadata.get("License-Expression")
    if expression:
        return [{"expression": expression}]
    license_text = distribution.metadata.get("License")
    normalized_license = " ".join((license_text or "").split())
    if (
        normalized_license
        and normalized_license.upper() != "UNKNOWN"
        and len(normalized_license) <= 200
    ):
        return [{"license": {"name": normalized_license}}]
    return None


def _component_for_distribution(distribution: metadata.Distribution) -> dict[str, Any]:
    name = distribution.metadata.get("Name") or distribution.name
    version = distribution.version
    component: dict[str, Any] = {
        "type": "library",
        "bom-ref": _purl(name, version),
        "name": name,
        "version": version,
        "purl": _purl(name, version),
    }
    licenses = _license_entry(distribution)
    if licenses:
        component["licenses"] = licenses
    homepage = distribution.metadata.get("Home-page")
    if homepage:
        component["externalReferences"] = [{"type": "website", "url": homepage}]
    return component


def _bundled_backend_component(repository_root: Path) -> dict[str, Any]:
    checksum_path = repository_root / "bundled" / "SHA256SUMS"
    properties = []
    pattern = re.compile(r"^([0-9a-fA-F]{64})\s+(.+)$")
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line.strip())
        if match:
            digest, filename = match.groups()
            properties.append(
                {
                    "name": f"kaito:bundled-file:{filename}:sha256",
                    "value": digest.lower(),
                }
            )
    return {
        "type": "application",
        "bom-ref": "pkg:generic/7-Zip@26.02",
        "name": "7-Zip",
        "version": "26.02",
        "purl": "pkg:generic/7-Zip@26.02",
        "supplier": {"name": "Igor Pavlov"},
        "properties": properties,
    }


def build_sbom(
    repository_root: Path,
    *,
    commit: str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    project = tomllib.loads(
        (repository_root / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    project_name = str(project["name"])
    project_version = str(project["version"])
    root_distribution = metadata.distribution(project_name)

    distributions: dict[str, metadata.Distribution] = {}
    dependency_graph: dict[str, list[str]] = {}
    queue: deque[metadata.Distribution] = deque([root_distribution])

    while queue:
        distribution = queue.popleft()
        canonical_name = canonicalize_name(
            distribution.metadata.get("Name") or distribution.name
        )
        if canonical_name in distributions:
            continue
        distributions[canonical_name] = distribution

        child_refs: list[str] = []
        for dependency_name in _active_requirements(distribution):
            try:
                child = metadata.distribution(dependency_name)
            except metadata.PackageNotFoundError as exc:
                raise RuntimeError(
                    f"Runtime dependency {dependency_name!r} required by {distribution.name!r} is not installed."
                ) from exc
            child_refs.append(
                _purl(child.metadata.get("Name") or child.name, child.version)
            )
            queue.append(child)
        dependency_graph[
            _purl(
                distribution.metadata.get("Name") or distribution.name,
                distribution.version,
            )
        ] = sorted(set(child_refs))

    root_ref = _purl(project_name, project_version)
    backend_component = _bundled_backend_component(repository_root)
    dependency_graph.setdefault(root_ref, []).append(backend_component["bom-ref"])
    dependency_graph[root_ref] = sorted(set(dependency_graph[root_ref]))
    dependency_graph.setdefault(backend_component["bom-ref"], [])

    components = [
        _component_for_distribution(distribution)
        for name, distribution in sorted(distributions.items())
        if name != canonicalize_name(project_name)
    ]
    components.append(backend_component)
    components.sort(key=lambda component: component["bom-ref"])

    timestamp = (generated_at or datetime.now(UTC)).astimezone(UTC)
    serial_seed = f"{project_name}:{project_version}:{commit}"
    serial_number = f"urn:uuid:{uuid.uuid5(CODE_NAMESPACE, serial_seed)}"

    return {
        "$schema": "https://cyclonedx.org/schema/bom-1.6.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": serial_number,
        "version": 1,
        "metadata": {
            "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "name": "kaito SBOM generator",
                        "version": "1",
                    }
                ]
            },
            "component": {
                "type": "application",
                "bom-ref": root_ref,
                "name": project_name,
                "version": project_version,
                "purl": root_ref,
                "properties": [
                    {"name": "kaito:source-commit", "value": commit},
                    {
                        "name": "kaito:python-version",
                        "value": platform.python_version(),
                    },
                ],
            },
        },
        "components": components,
        "dependencies": [
            {"ref": reference, "dependsOn": dependencies}
            for reference, dependencies in sorted(dependency_graph.items())
        ],
    }


def write_sbom(sbom: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(sbom, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    output_path.write_text(serialized, encoding="utf-8")
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    print(f"Wrote {output_path} ({digest})")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the kaito CycloneDX runtime SBOM."
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--commit", default="unknown")
    args = parser.parse_args()

    repository_root = args.repository_root.resolve()
    sbom = build_sbom(repository_root, commit=args.commit)
    write_sbom(sbom, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
