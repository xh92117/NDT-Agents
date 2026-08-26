"""Immutable application-owned model instructions shared across runtime layers."""

from __future__ import annotations

import hashlib
from typing import Literal, Self

from pydantic import Field, model_validator

from ndt_agents.contracts.v1 import StrictModel
from ndt_agents.models.registry import CatalogOrigin

APPLICATION_INSTRUCTION_VERSION: Literal["1.0.0"] = "1.0.0"


class ApplicationInstruction(StrictModel):
    schema_version: Literal["1.0.0"] = APPLICATION_INSTRUCTION_VERSION
    origin: Literal[CatalogOrigin.APPLICATION] = CatalogOrigin.APPLICATION
    instruction_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    instruction_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    text: str = Field(min_length=1, max_length=100_000)
    instruction_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        if self.instruction_sha256 != hashlib.sha256(self.text.encode("utf-8")).hexdigest():
            raise ValueError("application instruction hash is invalid")
        return self


def build_application_instruction(
    *,
    instruction_id: str,
    instruction_version: str,
    text: str,
) -> ApplicationInstruction:
    return ApplicationInstruction(
        instruction_id=instruction_id,
        instruction_version=instruction_version,
        text=text,
        instruction_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
