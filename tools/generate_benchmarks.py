"""Generate deterministic synthetic S0 benchmark case catalogs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_ROOT = ROOT / "benchmarks" / "v1"
ONTOLOGY = json.loads((ROOT / "domain" / "ontology.v1.json").read_text("utf-8"))

COMMON = {
    "benchmark_version": "1.0.0",
    "classification": "INTERNAL",
    "deidentification": "SYNTHETIC_NO_PERSONAL_DATA",
    "rights_basis": "PROJECT_GENERATED_SYNTHETIC",
    "training_use": "PROHIBITED",
}


def split_for(index: int, total: int) -> str:
    ratio = index / total
    if ratio <= 0.2:
        return "CALIBRATION"
    if ratio <= 0.5:
        return "DEVELOPMENT_EVAL"
    return "FROZEN_TEST"


def with_common(case_id: str, index: int, total: int, **fields: Any) -> dict[str, Any]:
    return {**COMMON, "case_id": case_id, "split": split_for(index, total), **fields}


def routing_cases() -> list[dict[str, Any]]:
    route_types = [
        (
            "GENERAL_SYNC",
            False,
            [],
            False,
            "organize supplied text; no professional specialization is required",
        ),
        (
            "ONE_PROFESSIONAL_SYNC_REVIEW",
            True,
            [{"assignment_id": "qa", "agent_type": "technical_qa", "depends_on": []}],
            False,
            "answer one technical NDT question and independently review the result",
        ),
        (
            "MULTIPLE_INDEPENDENT_ASYNC_REVIEW",
            True,
            [
                {"assignment_id": "qa", "agent_type": "technical_qa", "depends_on": []},
                {"assignment_id": "data", "agent_type": "data_processing", "depends_on": []},
                {"assignment_id": "method", "agent_type": "method_specialist", "depends_on": []},
            ],
            False,
            "run three explicitly independent professional analyses asynchronously and review all",
        ),
        (
            "MULTIPLE_DEPENDENT_ASYNC_REVIEW",
            True,
            [
                {"assignment_id": "plan", "agent_type": "inspection_plan", "depends_on": []},
                {
                    "assignment_id": "report",
                    "agent_type": "report",
                    "depends_on": ["plan"],
                },
            ],
            False,
            "prepare a plan, then draft a dependent report asynchronously, and review both",
        ),
        (
            "HUMAN_REQUIRED",
            True,
            [
                {
                    "assignment_id": "critical",
                    "agent_type": "technical_qa",
                    "depends_on": [],
                }
            ],
            True,
            "assess a critical formal conclusion that requires qualified human approval",
        ),
    ]
    cases: list[dict[str, Any]] = []
    for route_index, (
        route,
        review,
        assignments,
        human_required,
        request_template,
    ) in enumerate(route_types):
        for offset in range(1, 201):
            index = route_index * 200 + offset
            cases.append(
                with_common(
                    f"ROUTE-{index:04d}",
                    index,
                    1000,
                    expected={
                        "professional_agents": len(assignments),
                        "review_required": review,
                        "route": route,
                    },
                    request=f"Synthetic routing request {index}: {request_template}.",
                    review_status="MACHINE_GOLD",
                    route_signals={
                        "general_eligible": route == "GENERAL_SYNC",
                        "human_required": human_required,
                        "professional_assignments": assignments,
                    },
                )
            )
    return cases


def technical_qa_cases() -> list[dict[str, Any]]:
    methods = [item["code"] for item in ONTOLOGY["inspection_methods"]]
    structures = ONTOLOGY["structure_classes"]
    materials = ONTOLOGY["material_classes"]
    cases: list[dict[str, Any]] = []
    index = 0
    for method in methods:
        for structure in structures:
            for variant in range(1, 9):
                index += 1
                material = materials[(index - 1) % len(materials)]
                cases.append(
                    with_common(
                        f"QA-{index:04d}",
                        index,
                        288,
                        expected={
                            "citation_required": True,
                            "must_state_applicability": True,
                            "must_state_limitations": True,
                            "schema": "AgentResult@1.0.0",
                        },
                        material=material,
                        method=method,
                        question=(
                            f"Synthetic QA variant {variant}: assess applicability for {method}, "
                            f"{structure}, and {material}."
                        ),
                        review_status="PENDING_DOMAIN_EXPERT_GOLD",
                        structure_class=structure,
                    )
                )
    return cases


def inspection_plan_cases() -> list[dict[str, Any]]:
    scenarios = [
        "NEW_BUILD",
        "IN_SERVICE",
        "INCIDENT",
        "ACCEPTANCE",
        "MISSING_INPUTS",
        "CONFLICTING_CONSTRAINTS",
    ]
    cases: list[dict[str, Any]] = []
    for scenario_index, scenario in enumerate(scenarios):
        for offset in range(1, 11):
            index = scenario_index * 10 + offset
            cases.append(
                with_common(
                    f"PLAN-{index:03d}",
                    index,
                    60,
                    expected={
                        "human_approval_required": True,
                        "required_template": "TPL-INSPECTION-PLAN-V1",
                    },
                    request=f"Create synthetic inspection plan case {index} for {scenario}.",
                    review_status="PENDING_DOMAIN_EXPERT_GOLD",
                    scenario=scenario,
                )
            )
    return cases


def report_cases() -> list[dict[str, Any]]:
    report_types = ["SINGLE_METHOD", "MULTI_METHOD", "LIMITED_DATA", "CONFLICTING_RESULTS"]
    cases: list[dict[str, Any]] = []
    for report_index, report_type in enumerate(report_types):
        for offset in range(1, 11):
            index = report_index * 10 + offset
            cases.append(
                with_common(
                    f"REPORT-{index:03d}",
                    index,
                    40,
                    expected={
                        "formal_publication_allowed": False,
                        "required_template": "TPL-INSPECTION-REPORT-V1",
                        "source_traceability_required": True,
                    },
                    report_type=report_type,
                    request=f"Draft synthetic report case {index} for {report_type}.",
                    review_status="PENDING_DOMAIN_EXPERT_GOLD",
                )
            )
    return cases


def compression_restore_cases() -> list[dict[str, Any]]:
    levels = ["C0", "C1", "C2", "C3"]
    restore_modes = ["DIRECT", "INTENT", "PREVIEW_CONFIRM", "BRANCH"]
    cases: list[dict[str, Any]] = []
    for level_index, level in enumerate(levels):
        for offset in range(1, 51):
            index = level_index * 50 + offset
            cases.append(
                with_common(
                    f"COMPRESS-{index:04d}",
                    index,
                    200,
                    compression_level=level,
                    expected={
                        "critical_field_retention": 1.0,
                        "on_validation_failure": "LESS_AGGRESSIVE_OR_ORIGINAL",
                        "restore_mode": restore_modes[(index - 1) % len(restore_modes)],
                    },
                    protected_fields={
                        "approval_state": "PENDING",
                        "citation": "artifact://synthetic/source#clause-5.2",
                        "constraint": "maximum crack width 0.20 mm",
                        "source_sha256": "a" * 64,
                        "unresolved_issue": "applicable standard not approved",
                    },
                    review_status="MACHINE_GOLD",
                )
            )
    return cases


def bash_encoding_cases() -> list[dict[str, Any]]:
    encodings = ["UTF-8", "UTF-8-BOM", "GBK", "GB18030", "UTF-16LE", "MALFORMED"]
    path_types = ["SPACES", "CHINESE", "LEADING_DASH", "LONG_PATH", "MIXED_NORMALIZATION"]
    cases: list[dict[str, Any]] = []
    index = 0
    for encoding in encodings:
        for path_type in path_types:
            for variant in range(1, 11):
                index += 1
                expected_status = "MANUAL_REVIEW" if encoding == "MALFORMED" else "ROUND_TRIP"
                cases.append(
                    with_common(
                        f"ENCODING-{index:04d}",
                        index,
                        300,
                        encoding=encoding,
                        expected={
                            "lossy_conversion_allowed": False,
                            "status": expected_status,
                        },
                        path_type=path_type,
                        review_status="MACHINE_GOLD",
                        text=(f"Synthetic path/text case {variant}; Chinese characters: 桥梁检测."),
                    )
                )
    return cases


def fault_cases() -> list[dict[str, Any]]:
    faults = [
        "LLM_TIMEOUT",
        "TOOL_TIMEOUT",
        "INVALID_INPUT_SCHEMA",
        "INVALID_OUTPUT_SCHEMA",
        "PROCESS_CRASH",
        "MCP_DISCONNECT",
        "STORAGE_UNAVAILABLE",
        "QUEUE_DUPLICATE",
        "PARTIAL_OUTPUT",
        "CHECKPOINT_CONFLICT",
        "KEY_UNAVAILABLE",
        "BUDGET_EXHAUSTED",
    ]
    cases: list[dict[str, Any]] = []
    for fault_index, fault in enumerate(faults):
        for offset in range(1, 11):
            index = fault_index * 10 + offset
            cases.append(
                with_common(
                    f"FAULT-{index:04d}",
                    index,
                    120,
                    expected={
                        "duplicate_side_effects": 0,
                        "state": "TYPED_PARTIAL_OR_FAILURE",
                    },
                    fault=fault,
                    review_status="MACHINE_GOLD",
                )
            )
    return cases


def tenant_isolation_cases() -> list[dict[str, Any]]:
    layers = [
        "API",
        "SQL",
        "VECTOR",
        "CACHE",
        "ARTIFACT",
        "LOG",
        "TASK",
        "MEMORY",
        "SNAPSHOT",
        "QUEUE",
    ]
    cases: list[dict[str, Any]] = []
    for layer_index, layer in enumerate(layers):
        for offset in range(1, 101):
            index = layer_index * 100 + offset
            cases.append(
                with_common(
                    f"TENANT-{index:04d}",
                    index,
                    1000,
                    attack="FORGED_TARGET_SCOPE",
                    expected={"audit_required": True, "decision": "DENY", "leaked_objects": 0},
                    layer=layer,
                    review_status="MACHINE_GOLD",
                    source_tenant="00000000-0000-4000-8000-000000000001",
                    target_tenant="00000000-0000-4000-8000-000000000099",
                )
            )
    return cases


def write_jsonl(path: Path, cases: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(json.dumps(case, sort_keys=True) + "\n" for case in cases)
    path.write_text(content, encoding="utf-8", newline="\n")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    datasets = {
        "routing": routing_cases(),
        "technical-qa": technical_qa_cases(),
        "inspection-plan": inspection_plan_cases(),
        "report": report_cases(),
        "compression-restore": compression_restore_cases(),
        "bash-encoding": bash_encoding_cases(),
        "fault": fault_cases(),
        "tenant-isolation": tenant_isolation_cases(),
    }
    entries: list[dict[str, Any]] = []
    for name, cases in datasets.items():
        path = BENCHMARK_ROOT / f"{name}.jsonl"
        write_jsonl(path, cases)
        entries.append(
            {
                "case_count": len(cases),
                "dataset": name,
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": sha256(path),
                "splits": {
                    split: sum(case["split"] == split for case in cases)
                    for split in ("CALIBRATION", "DEVELOPMENT_EVAL", "FROZEN_TEST")
                },
            }
        )
    manifest = {
        "benchmark_version": "1.0.0",
        "datasets": entries,
        "rights_basis": "PROJECT_GENERATED_SYNTHETIC",
        "state": "PENDING_EXPERT_ADJUDICATION_AND_REAL_DATA",
        "training_use": "PROHIBITED",
    }
    (BENCHMARK_ROOT / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
