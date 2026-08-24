"""Capture official PyPI release metadata for the exact locked SBOM components."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
SBOM_PATH = ROOT / "sbom" / "cyclonedx.v1.json"
LOCK_PATH = ROOT / "uv.lock"
EVIDENCE_PATH = ROOT / "security" / "license-evidence.v1.json"
PYPI_JSON_API_DOC = "https://docs.pypi.org/api/json/"
LICENSE_METADATA_SPEC = "https://packaging.python.org/en/latest/specifications/core-metadata/"
USER_AGENT = "ndt-agents-license-evidence/1.0 (+https://github.com/xh92117/NDT-Agents)"
MAX_RESPONSE_BYTES = 5_000_000


class LicenseEvidenceError(RuntimeError):
    """Raised when official metadata cannot be captured or validated safely."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def classify_evidence_state(
    license_expression: str,
    legacy_license: str,
    license_classifiers: list[str],
) -> str:
    """Classify metadata without inferring a legal conclusion from legacy fields."""

    if license_expression.strip():
        return "SPDX_EXPRESSION"
    if legacy_license.strip() or license_classifiers:
        return "LEGACY_METADATA_REQUIRES_TEXT_REVIEW"
    return "MISSING_LICENSE_METADATA"


def require_mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LicenseEvidenceError(f"{label} must be a JSON object")
    return cast(dict[str, Any], value)


def read_json(path: Path) -> dict[str, Any]:
    return require_mapping(json.loads(path.read_text("utf-8")), path.as_posix())


def component_scope(component: dict[str, Any]) -> str:
    properties = component.get("properties")
    if not isinstance(properties, list):
        raise LicenseEvidenceError(f"missing scope properties for {component.get('purl')}")
    for value in properties:
        if isinstance(value, dict) and value.get("name") == "ndt:dependency-scope":
            scope = value.get("value")
            if isinstance(scope, str) and scope:
                return scope
    raise LicenseEvidenceError(f"missing dependency scope for {component.get('purl')}")


def release_url(name: str, version: str) -> str:
    encoded_name = urllib.parse.quote(name, safe="")
    encoded_version = urllib.parse.quote(version, safe="")
    return f"https://pypi.org/pypi/{encoded_name}/{encoded_version}/json"


def fetch_raw(url: str, timeout_seconds: float, attempts: int = 2) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        method="GET",
    )
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                status = getattr(response, "status", None)
                if status != 200:
                    raise LicenseEvidenceError(f"{url} returned HTTP {status}")
                content = cast(bytes, response.read(MAX_RESPONSE_BYTES + 1))
                if len(content) > MAX_RESPONSE_BYTES:
                    raise LicenseEvidenceError(
                        f"{url} exceeded the {MAX_RESPONSE_BYTES}-byte response limit"
                    )
                return content
        except (OSError, TimeoutError, urllib.error.URLError, LicenseEvidenceError) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(0.25)
    raise LicenseEvidenceError(f"failed to retrieve {url} after {attempts} attempts: {last_error}")


def capture_component(component: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    name = component.get("name")
    version = component.get("version")
    purl = component.get("purl")
    if not all(isinstance(value, str) and value for value in (name, version, purl)):
        raise LicenseEvidenceError("SBOM component must contain name, version, and purl")
    assert isinstance(name, str)
    assert isinstance(version, str)
    assert isinstance(purl, str)

    url = release_url(name, version)
    raw = fetch_raw(url, timeout_seconds)
    payload = require_mapping(json.loads(raw), url)
    info = require_mapping(payload.get("info"), f"{url} info")
    returned_name = info.get("name")
    returned_version = info.get("version")
    if not isinstance(returned_name, str) or canonical_name(returned_name) != canonical_name(name):
        raise LicenseEvidenceError(f"{url} returned mismatched project name {returned_name!r}")
    if returned_version != version:
        raise LicenseEvidenceError(f"{url} returned mismatched version {returned_version!r}")

    expression_value = info.get("license_expression")
    license_expression = expression_value.strip() if isinstance(expression_value, str) else ""
    legacy_value = info.get("license")
    legacy_license = legacy_value if isinstance(legacy_value, str) else ""
    classifier_values = info.get("classifiers")
    classifiers = (
        sorted(
            value
            for value in classifier_values
            if isinstance(value, str) and value.startswith("License ::")
        )
        if isinstance(classifier_values, list)
        else []
    )
    legacy_bytes = legacy_license.encode("utf-8")
    return {
        "evidence_state": classify_evidence_state(license_expression, legacy_license, classifiers),
        "legacy_license": {
            "sha256": sha256_bytes(legacy_bytes),
            "utf8_bytes": len(legacy_bytes),
            "value": legacy_license or None,
        },
        "license_classifiers": classifiers,
        "license_expression": license_expression or None,
        "name": name,
        "purl": purl,
        "scope": component_scope(component),
        "source_response_sha256": sha256_bytes(raw),
        "source_url": url,
        "version": version,
    }


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_snapshot(*, captured_at: str, timeout_seconds: float, workers: int) -> dict[str, Any]:
    sbom = read_json(SBOM_PATH)
    raw_components = sbom.get("components")
    if not isinstance(raw_components, list) or not raw_components:
        raise LicenseEvidenceError("SBOM components must be a non-empty array")
    components = [require_mapping(value, "SBOM component") for value in raw_components]

    captured: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(capture_component, component, timeout_seconds): component
            for component in components
        }
        for future in as_completed(futures):
            component = futures[future]
            try:
                captured.append(future.result())
            except Exception as exc:
                purl = component.get("purl", "unknown")
                raise LicenseEvidenceError(f"capture failed for {purl}: {exc}") from exc

    captured.sort(key=lambda value: cast(str, value["purl"]))
    counts = {
        state: sum(item["evidence_state"] == state for item in captured)
        for state in (
            "SPDX_EXPRESSION",
            "LEGACY_METADATA_REQUIRES_TEXT_REVIEW",
            "MISSING_LICENSE_METADATA",
        )
    }
    return {
        "approval": {
            "required_roles": ["LEGAL_OWNER", "SECURITY_OWNER"],
            "state": "EVIDENCE_ONLY_PENDING_HUMAN_REVIEW",
        },
        "captured_at": captured_at,
        "components": captured,
        "evidence_version": "1.0.0",
        "policy": {
            "automatic_approval": False,
            "license_metadata_specification": LICENSE_METADATA_SPEC,
            "metadata_source": "PYPI_VERSION_JSON",
            "source_api_documentation": PYPI_JSON_API_DOC,
        },
        "sbom_path": SBOM_PATH.relative_to(ROOT).as_posix(),
        "sbom_sha256": sha256(SBOM_PATH),
        "summary": {
            "component_count": len(captured),
            "legacy_metadata_review_count": counts["LEGACY_METADATA_REQUIRES_TEXT_REVIEW"],
            "missing_license_metadata_count": counts["MISSING_LICENSE_METADATA"],
            "spdx_expression_count": counts["SPDX_EXPRESSION"],
        },
        "uv_lock_path": LOCK_PATH.relative_to(ROOT).as_posix(),
        "uv_lock_sha256": sha256(LOCK_PATH),
    }


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captured-at", default=utc_now())
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    if not 1 <= args.workers <= 16:
        parser.error("--workers must be between 1 and 16")
    return args


def main() -> None:
    args = parse_args()
    snapshot = build_snapshot(
        captured_at=cast(str, args.captured_at),
        timeout_seconds=cast(float, args.timeout_seconds),
        workers=cast(int, args.workers),
    )
    write_json_atomic(EVIDENCE_PATH, snapshot)
    summary = snapshot["summary"]
    print(
        "LICENSE_EVIDENCE=CAPTURED "
        f"components={summary['component_count']} "
        f"spdx={summary['spdx_expression_count']} "
        f"legacy={summary['legacy_metadata_review_count']} "
        f"missing={summary['missing_license_metadata_count']}"
    )


if __name__ == "__main__":
    main()
