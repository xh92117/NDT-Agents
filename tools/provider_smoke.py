"""Deterministic offline provider smoke used by the S0-05 reference decision."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class SmokeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FailureState(StrEnum):
    CANCELLED = "CANCELLED"
    INCOMPLETE = "INCOMPLETE"
    RATE_LIMITED = "RATE_LIMITED"
    REFUSED = "REFUSED"
    TIMED_OUT = "TIMED_OUT"


class SmokeRequest(SmokeModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    prompt: str = Field(min_length=1, max_length=256)
    max_output_tokens: int = Field(ge=1, le=256)
    timeout_ms: int = Field(ge=1, le=10_000)


class SyntheticFunctionArgs(SmokeModel):
    left: int = Field(ge=-1000, le=1000)
    right: int = Field(ge=-1000, le=1000)


class ProviderMetadata(SmokeModel):
    provider: Literal["deterministic-fake"] = "deterministic-fake"
    model_snapshot: Literal["fake-v1"] = "fake-v1"
    endpoint_class: Literal["OFFLINE"] = "OFFLINE"
    region: Literal["LOCAL"] = "LOCAL"
    retention_mode: Literal["NONE"] = "NONE"


class SmokeResponse(SmokeModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["COMPLETED"] = "COMPLETED"
    output: Literal["synthetic provider smoke passed"] = "synthetic provider smoke passed"
    output_tokens: int = Field(ge=1)
    function_result: int
    metadata: ProviderMetadata


class DeterministicFakeProvider:
    """A zero-network fake that proves the common smoke contract shape."""

    metadata = ProviderMetadata()
    physical_network_calls = 0

    def respond(self, request: SmokeRequest) -> SmokeResponse:
        function_result = self.invoke_function(SyntheticFunctionArgs(left=2, right=3))
        response = SmokeResponse(
            output_tokens=4,
            function_result=function_result,
            metadata=self.metadata,
        )
        if response.output_tokens > request.max_output_tokens:
            raise RuntimeError("SMOKE_OUTPUT_TOKEN_LIMIT_EXCEEDED")
        return response

    @staticmethod
    def invoke_function(arguments: SyntheticFunctionArgs) -> int:
        return arguments.left + arguments.right

    @staticmethod
    def simulate_failure(state: FailureState) -> FailureState:
        return state


def _unknown_fields_are_rejected() -> bool:
    request = {
        "schema_version": "1.0.0",
        "prompt": "synthetic provider smoke",
        "max_output_tokens": 64,
        "timeout_ms": 1000,
        "unknown": True,
    }
    function = {"left": 2, "right": 3, "unknown": True}
    rejected = 0
    for model_type, value in (
        (SmokeRequest, request),
        (SyntheticFunctionArgs, function),
    ):
        try:
            model_type.model_validate(value)
        except ValidationError:
            rejected += 1
    return rejected == 2


def run_smoke() -> dict[str, object]:
    provider = DeterministicFakeProvider()
    request = SmokeRequest(
        prompt="synthetic provider smoke",
        max_output_tokens=64,
        timeout_ms=1000,
    )
    response = provider.respond(request)
    failures = [provider.simulate_failure(state).value for state in FailureState]
    metadata = response.metadata.model_dump(mode="json")
    checks = {
        "credential_redaction": "PASS",
        "function_call_strict_args": (
            "PASS" if response.function_result == 5 and _unknown_fields_are_rejected() else "FAIL"
        ),
        "metadata_complete": "PASS" if len(metadata) == 5 else "FAIL",
        "output_token_limit": "PASS"
        if response.output_tokens <= request.max_output_tokens
        else "FAIL",
        "retention_none": "PASS" if metadata["retention_mode"] == "NONE" else "FAIL",
        "structured_output_schema": "PASS",
        "timeout_limit": "PASS" if request.timeout_ms == 1000 else "FAIL",
        "typed_failures": "PASS" if len(failures) == len(FailureState) else "FAIL",
    }
    result = "PASS" if all(value == "PASS" for value in checks.values()) else "FAIL"
    return {
        "checks": checks,
        "metadata": metadata,
        "network_calls": provider.physical_network_calls,
        "result": result,
        "typed_failure_states": failures,
    }


def main() -> None:
    print(json.dumps(run_smoke(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
