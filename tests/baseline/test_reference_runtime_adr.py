"""Consistency checks for the proposed S0-05 reference-runtime ADR."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADR = (ROOT / "docs" / "decisions" / "ADR-0001-reference-runtime.md").read_text("utf-8")


def test_adr_is_not_misrepresented_as_accepted() -> None:
    assert "PROPOSED_BLOCKED_BY_S0-10_APPROVAL" in ADR
    assert "This ADR becomes `ACCEPTED` only when" in ADR


def test_adr_preserves_provider_and_domain_boundaries() -> None:
    for required in (
        "ModelPort",
        "OrchestrationPort",
        "ToolRegistryPort",
        "ApprovalPort",
        "AuditPort",
        "Provider SDK objects and LangGraph state must not leak",
    ):
        assert required in ADR


def test_adr_defines_provider_smoke_and_hardware_profiles() -> None:
    for required in (
        "DEV-CPU-1",
        "CI-CPU-1",
        "PARSER-GPU-1",
        "PROD-APP-1",
        "LOCAL-LLM-1",
        "Provider smoke-test specification",
        "deterministic fake model",
    ):
        assert required in ADR
