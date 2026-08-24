"""Generate checked-in JSON Schemas and deterministic examples for V1 contracts."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ndt_agents.contracts.v1 import (  # noqa: E402
    AgentResult,
    AgentStatus,
    ApprovalOutcome,
    ApprovalRecord,
    ArtifactRef,
    BudgetPolicy,
    CacheEntry,
    Checkpoint,
    CitationRef,
    DataClassification,
    Limit,
    MemoryRecord,
    MemoryScope,
    ReviewDecision,
    ReviewResult,
    RiskLevel,
    TaskContext,
    TenantScope,
    ToolResult,
    ToolStatus,
)

SCHEMA_DIR = ROOT / "schemas" / "v1"
EXAMPLE_DIR = ROOT / "examples" / "contracts" / "v1"
SCHEMA_BASE = "https://schemas.ndt-agents.local/v1/"

CONTRACTS: dict[str, type[BaseModel]] = {
    "tenant-scope": TenantScope,
    "budget-policy": BudgetPolicy,
    "artifact": ArtifactRef,
    "citation": CitationRef,
    "task-context": TaskContext,
    "agent-result": AgentResult,
    "tool-result": ToolResult,
    "checkpoint": Checkpoint,
    "memory-record": MemoryRecord,
    "cache-entry": CacheEntry,
    "review-result": ReviewResult,
    "approval-record": ApprovalRecord,
}

NOW = datetime(2026, 8, 21, 12, 0, 0, tzinfo=UTC)
TENANT_ID = UUID("00000000-0000-4000-8000-000000000001")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000002")
USER_ID = UUID("00000000-0000-4000-8000-000000000003")
TASK_ID = UUID("00000000-0000-4000-8000-000000000004")
RUN_ID = UUID("00000000-0000-4000-8000-000000000005")
ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000000006")
HASH_A = "a" * 64
HASH_B = "b" * 64


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def examples() -> dict[str, Any]:
    scope = TenantScope(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        user_id=USER_ID,
        role_codes=("NDT_ENGINEER",),
        permission_version="perm-1",
    )
    limit = Limit(default=1, active=1, hard=2)
    budget = BudgetPolicy(
        policy_id="budget-p1-v1",
        task_class="P1",
        graph_steps=limit,
        llm_calls=limit,
        tool_calls=limit,
        total_tokens=Limit(default=10000, active=10000, hard=20000),
        wall_time_ms=Limit(default=120000, active=120000, hard=300000),
        professional_concurrency=Limit(default=1, active=1, hard=1),
        review_rounds=limit,
        correction_rounds=limit,
    )
    artifact = ArtifactRef(
        artifact_id=ARTIFACT_ID,
        scope=scope,
        artifact_version="1",
        uri="artifact://tenant/project/example",
        media_type="application/json",
        size_bytes=128,
        sha256=HASH_A,
        classification=DataClassification.INTERNAL,
        immutable=True,
    )
    citation = CitationRef(
        citation_id=UUID("00000000-0000-4000-8000-000000000007"),
        artifact_id=ARTIFACT_ID,
        source_sha256=HASH_A,
        locator_type="CLAUSE",
        locator="5.2.1",
        claim_id="claim-1",
    )
    task = TaskContext(
        task_id=TASK_ID,
        scope=scope,
        task_class="P1",
        goal="Assess the supplied synthetic observation.",
        success_criteria=("Return a typed result.",),
        risk_level=RiskLevel.MEDIUM,
        dependency_data={},
        context_manifest_sha256=HASH_B,
        artifacts=(artifact,),
        skill_versions={"technical-qa": "1.0.0"},
        prompt_versions={"qa": "1.0.0"},
        model_versions={"reasoning": "reference"},
        knowledge_versions=("synthetic-1",),
        allowed_tools=("artifact.read@1",),
        budget=budget,
        output_schema_id=SCHEMA_BASE + "agent-result.schema.json",
        review_checklist=("schema", "evidence"),
        created_at=NOW,
    )
    agent = AgentResult(
        task_id=TASK_ID,
        run_id=RUN_ID,
        status=AgentStatus.SUCCESS,
        summary="Synthetic result produced.",
        structured_data={"synthetic": True},
        artifacts=(artifact,),
        evidence=(citation,),
        confidence=0.8,
        issues=(),
        retryable=False,
        failure_code=None,
        completed_at=NOW,
    )
    tool = ToolResult(
        call_id=UUID("00000000-0000-4000-8000-000000000008"),
        task_id=TASK_ID,
        run_id=RUN_ID,
        scope=scope,
        tool_name="artifact.read",
        tool_version="1.0.0",
        status=ToolStatus.SUCCESS,
        output={"synthetic": True},
        exit_code=0,
        stdout="",
        stderr="",
        encoding="utf-8",
        truncated=False,
        artifacts=(artifact,),
        idempotency_key=None,
        input_sha256=HASH_A,
        output_sha256=HASH_B,
        error_code=None,
        retryable=False,
        duration_ms=10,
        completed_at=NOW,
    )
    checkpoint = Checkpoint(
        checkpoint_id=UUID("00000000-0000-4000-8000-000000000009"),
        task_id=TASK_ID,
        scope=scope,
        sequence=1,
        graph_version="main-graph-1",
        state_schema_version="1.0.0",
        state_artifact=artifact,
        state_sha256=HASH_B,
        committed_side_effect_ids=(),
        created_at=NOW,
    )
    memory = MemoryRecord(
        memory_id=UUID("00000000-0000-4000-8000-000000000010"),
        scope=scope,
        memory_scope=MemoryScope.PROJECT,
        content={"fact": "synthetic"},
        provenance_ids=(ARTIFACT_ID,),
        confidence=1.0,
        classification=DataClassification.INTERNAL,
        approval_state="CANDIDATE",
        expires_at=NOW + timedelta(days=30),
        created_at=NOW,
    )
    cache = CacheEntry(
        cache_entry_id=UUID("00000000-0000-4000-8000-000000000011"),
        scope=scope,
        cache_class="EXACT",
        cache_key_sha256=HASH_A,
        permission_version="perm-1",
        version_manifest={"model": "reference", "prompt": "1.0.0"},
        value_artifact=artifact,
        validation_state="VALID",
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    review = ReviewResult(
        review_id=UUID("00000000-0000-4000-8000-000000000012"),
        task_id=TASK_ID,
        target_run_id=RUN_ID,
        target_sha256=HASH_A,
        reviewer_version="review-1",
        decision=ReviewDecision.PASS,
        findings=(),
        correction_count=0,
        completed_at=NOW,
    )
    approval = ApprovalRecord(
        approval_id=UUID("00000000-0000-4000-8000-000000000013"),
        scope=scope,
        action="PUBLISH_KNOWLEDGE",
        target_type="KNOWLEDGE_VERSION",
        target_id=ARTIFACT_ID,
        target_version="1",
        target_sha256=HASH_A,
        policy_version="approval-1",
        actor_id=USER_ID,
        outcome=ApprovalOutcome.APPROVED,
        reason="Synthetic contract example.",
        decided_at=NOW,
        expires_at=None,
    )
    return {
        "tenant-scope": scope,
        "budget-policy": budget,
        "artifact": artifact,
        "citation": citation,
        "task-context": task,
        "agent-result": agent,
        "tool-result": tool,
        "checkpoint": checkpoint,
        "memory-record": memory,
        "cache-entry": cache,
        "review-result": review,
        "approval-record": approval,
    }


def main() -> None:
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    EXAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    valid_examples = examples()
    manifest_entries: list[dict[str, str]] = []

    for name, model in CONTRACTS.items():
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = SCHEMA_BASE + f"{name}.schema.json"
        schema["x-contract-version"] = "1.0.0"
        schema_path = SCHEMA_DIR / f"{name}.schema.json"
        write_json(schema_path, schema)

        valid = valid_examples[name].model_dump(mode="json")
        valid_path = EXAMPLE_DIR / f"{name}.valid.json"
        write_json(valid_path, valid)

        invalid = dict(valid)
        invalid["unexpected_field"] = "must be rejected"
        invalid_path = EXAMPLE_DIR / f"{name}.invalid-extra-field.json"
        write_json(invalid_path, invalid)

        digest = hashlib.sha256(schema_path.read_bytes()).hexdigest()
        manifest_entries.append(
            {
                "contract": name,
                "schema": schema_path.relative_to(ROOT).as_posix(),
                "schema_sha256": digest,
                "valid_example": valid_path.relative_to(ROOT).as_posix(),
                "invalid_example": invalid_path.relative_to(ROOT).as_posix(),
            }
        )

    write_json(
        SCHEMA_DIR / "manifest.json",
        {
            "manifest_version": "1.0.0",
            "generated_by": "tools/generate_schemas.py",
            "contracts": manifest_entries,
        },
    )


if __name__ == "__main__":
    main()
