"""Contract and JSON Schema tests for S0-04."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ndt_agents.contracts.v1 import AgentResult, Limit

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = json.loads((ROOT / "schemas" / "v1" / "manifest.json").read_text("utf-8"))


@pytest.mark.parametrize("entry", MANIFEST["contracts"], ids=lambda entry: entry["contract"])
def test_valid_examples_satisfy_json_schema(entry: dict[str, str]) -> None:
    schema = json.loads((ROOT / entry["schema"]).read_text("utf-8"))
    instance = json.loads((ROOT / entry["valid_example"]).read_text("utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(instance)


@pytest.mark.parametrize("entry", MANIFEST["contracts"], ids=lambda entry: entry["contract"])
def test_unknown_fields_are_rejected(entry: dict[str, str]) -> None:
    schema = json.loads((ROOT / entry["schema"]).read_text("utf-8"))
    instance = json.loads((ROOT / entry["invalid_example"]).read_text("utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(instance))
    assert errors, f"{entry['contract']} accepted an unknown field"


def test_limit_order_is_enforced() -> None:
    with pytest.raises(ValidationError):
        Limit(default=2, active=1, hard=3)


def test_failed_agent_result_requires_failure_code() -> None:
    entry = next(item for item in MANIFEST["contracts"] if item["contract"] == "agent-result")
    value = json.loads((ROOT / entry["valid_example"]).read_text("utf-8"))
    value["status"] = "FAILED"
    with pytest.raises(ValidationError):
        AgentResult.model_validate(value)


def test_all_contracts_are_v1_and_strict() -> None:
    assert len(MANIFEST["contracts"]) == 12
    for entry in MANIFEST["contracts"]:
        schema = json.loads((ROOT / entry["schema"]).read_text("utf-8"))
        assert schema["x-contract-version"] == "1.0.0"
        assert schema["additionalProperties"] is False
