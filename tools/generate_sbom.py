"""Generate a deterministic CycloneDX inventory and pending license decisions from uv.lock."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "uv.lock"
PROJECT_PATH = ROOT / "pyproject.toml"
SBOM_PATH = ROOT / "sbom" / "cyclonedx.v1.json"
DECISION_PATH = ROOT / "security" / "license-decisions.v1.json"


def dependency_name(specifier: str) -> str:
    return re.split(r"[<>=!~;\s\[]", specifier, maxsplit=1)[0].lower().replace("_", "-")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def component_for(
    package: dict[str, Any], runtime: set[str], development: set[str]
) -> dict[str, Any]:
    name = str(package["name"])
    version = str(package["version"])
    normalized = name.lower().replace("_", "-")
    purl = f"pkg:pypi/{normalized}@{version}"
    if normalized in runtime:
        scope = "RUNTIME_DIRECT"
    elif normalized in development:
        scope = "DEVELOPMENT_DIRECT"
    else:
        scope = "TRANSITIVE"
    component: dict[str, Any] = {
        "bom-ref": purl,
        "name": name,
        "properties": [{"name": "ndt:dependency-scope", "value": scope}],
        "purl": purl,
        "type": "library",
        "version": version,
    }
    source = package.get("source", {})
    if "registry" in source:
        component["externalReferences"] = [{"type": "distribution", "url": str(source["registry"])}]
    sdist = package.get("sdist")
    if sdist and str(sdist.get("hash", "")).startswith("sha256:"):
        component["hashes"] = [
            {"alg": "SHA-256", "content": str(sdist["hash"]).removeprefix("sha256:")}
        ]
    return component


def main() -> None:
    lock = tomllib.loads(LOCK_PATH.read_text("utf-8"))
    project = tomllib.loads(PROJECT_PATH.read_text("utf-8"))
    runtime = {dependency_name(item) for item in project["project"]["dependencies"]}
    development = {dependency_name(item) for item in project["dependency-groups"].get("dev", [])}
    packages = [
        package
        for package in lock["package"]
        if package["name"] != project["project"]["name"] and "version" in package
    ]
    components = sorted(
        (component_for(package, runtime, development) for package in packages),
        key=lambda component: component["bom-ref"],
    )
    lock_hash = sha256(LOCK_PATH)
    sbom = {
        "bomFormat": "CycloneDX",
        "components": components,
        "metadata": {
            "component": {
                "bom-ref": "pkg:pypi/ndt-agents@0.1.0",
                "name": "ndt-agents",
                "type": "application",
                "version": "0.1.0",
            },
            "properties": [{"name": "ndt:uv-lock-sha256", "value": lock_hash}],
            "timestamp": "2026-08-21T12:00:00Z",
            "tools": {
                "components": [
                    {
                        "name": "tools/generate_sbom.py",
                        "type": "application",
                        "version": "1.0.0",
                    }
                ]
            },
        },
        "serialNumber": f"urn:uuid:{uuid5(NAMESPACE_URL, lock_hash)}",
        "specVersion": "1.6",
        "version": 1,
    }
    write_json(SBOM_PATH, sbom)

    decisions = {
        "approval": {
            "required_roles": ["LEGAL_OWNER", "SECURITY_OWNER"],
            "state": "PENDING_HUMAN_REVIEW",
        },
        "components": [
            {
                "decision": "PENDING",
                "declared_license": "UNKNOWN_PENDING_METADATA_AND_TEXT_REVIEW",
                "name": component["name"],
                "purl": component["purl"],
                "replacement_path": "REQUIRED_BEFORE_PRODUCTION_APPROVAL",
                "scope": component["properties"][0]["value"],
                "version": component["version"],
            }
            for component in components
        ],
        "inventory_version": "1.0.0",
        "sbom_path": SBOM_PATH.relative_to(ROOT).as_posix(),
        "sbom_sha256": sha256(SBOM_PATH),
    }
    write_json(DECISION_PATH, decisions)


if __name__ == "__main__":
    main()
