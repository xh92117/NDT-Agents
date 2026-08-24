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
LICENSE_EVIDENCE_PATH = ROOT / "security" / "license-evidence.v1.json"


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


def license_evidence_by_purl(expected_sbom_hash: str) -> dict[str, dict[str, Any]]:
    evidence: dict[str, Any] = json.loads(LICENSE_EVIDENCE_PATH.read_text("utf-8"))
    if evidence.get("sbom_sha256") != expected_sbom_hash:
        raise ValueError("license evidence is not bound to the generated SBOM")
    components = evidence.get("components")
    if not isinstance(components, list):
        raise ValueError("license evidence components must be a list")
    by_purl: dict[str, dict[str, Any]] = {}
    for value in components:
        if not isinstance(value, dict):
            raise ValueError("license evidence component must be an object")
        component = dict(value)
        purl = component.get("purl")
        if not isinstance(purl, str) or not purl or purl in by_purl:
            raise ValueError("license evidence purls must be unique non-empty strings")
        by_purl[purl] = component
    return by_purl


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

    sbom_hash = sha256(SBOM_PATH)
    evidence_by_purl = license_evidence_by_purl(sbom_hash)
    component_purls = {str(component["purl"]) for component in components}
    if set(evidence_by_purl) != component_purls:
        raise ValueError("license evidence must cover the exact generated SBOM component set")

    license_components: list[dict[str, Any]] = []
    for component in components:
        purl = str(component["purl"])
        evidence = evidence_by_purl[purl]
        expression = evidence.get("license_expression")
        evidence_state = evidence.get("evidence_state")
        source_url = evidence.get("source_url")
        scope = component["properties"][0]["value"]
        if expression is not None and not isinstance(expression, str):
            raise ValueError(f"invalid license expression for {purl}")
        if not isinstance(evidence_state, str) or not isinstance(source_url, str):
            raise ValueError(f"incomplete license evidence for {purl}")
        if (
            evidence.get("name") != component["name"]
            or evidence.get("version") != component["version"]
            or evidence.get("scope") != scope
        ):
            raise ValueError(f"license evidence identity or scope mismatch for {purl}")
        license_components.append(
            {
                "decision": "PENDING",
                "declared_license": expression or evidence_state,
                "license_evidence_state": evidence_state,
                "license_source_url": source_url,
                "name": component["name"],
                "purl": purl,
                "replacement_path": "REQUIRED_BEFORE_PRODUCTION_APPROVAL",
                "scope": scope,
                "version": component["version"],
            }
        )

    decisions = {
        "approval": {
            "required_roles": ["LEGAL_OWNER", "SECURITY_OWNER"],
            "state": "PENDING_HUMAN_REVIEW",
        },
        "components": license_components,
        "inventory_version": "1.1.0",
        "license_evidence_path": LICENSE_EVIDENCE_PATH.relative_to(ROOT).as_posix(),
        "license_evidence_sha256": sha256(LICENSE_EVIDENCE_PATH),
        "sbom_path": SBOM_PATH.relative_to(ROOT).as_posix(),
        "sbom_sha256": sbom_hash,
    }
    write_json(DECISION_PATH, decisions)


if __name__ == "__main__":
    main()
