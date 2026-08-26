"""S6-08 seven-day shadow deployment and expert-pilot evidence state machine."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from ndt_agents.contracts.v1 import StrictModel


class PilotEvidenceClass(StrEnum):
    SYNTHETIC = "SYNTHETIC"
    LIVE = "LIVE"


class DailyGateState(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class ShadowPilotProfile(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    profile_version: str = "s6-shadow-pilot-1"
    required_days: Literal[7] = 7
    minimum_elapsed_hours: Literal[144] = 144
    required_expert_reviews: Literal[2] = 2
    critical_pass_rate: float = Field(default=1.0, ge=1.0, le=1.0)
    noncritical_pass_rate: float = Field(default=0.98, ge=0.98, le=0.98)


class ShadowDailyRecord(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    service_date: date
    started_at: datetime
    ended_at: datetime
    recorded_at: datetime
    build_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    assurance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    performance_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    budget_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    workload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    environment_id: str = Field(min_length=1, max_length=128)
    environment_approved: bool
    immutable_build: bool
    evidence_class: PilotEvidenceClass
    task_count: int = Field(ge=1)
    expert_visible_cases: int = Field(ge=1)
    critical_total: int = Field(ge=1)
    critical_passed: int = Field(ge=0)
    noncritical_total: int = Field(ge=1)
    noncritical_passed: int = Field(ge=0)
    security_state: DailyGateState
    resilience_state: DailyGateState
    performance_state: DailyGateState
    token_state: DailyGateState
    p0_findings: int = Field(ge=0)
    p1_findings: int = Field(ge=0)
    tenant_leaks: int = Field(ge=0)
    duplicate_committed_side_effects: int = Field(ge=0)
    correctness_failures: int = Field(ge=0)
    isolation_failures: int = Field(ge=0)
    evidence_uri: str = Field(min_length=1, max_length=1024)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_record_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        for value in (self.started_at, self.ended_at, self.recorded_at):
            if value.tzinfo is None or value.utcoffset() != timedelta(0):
                raise ValueError("pilot timestamps must use UTC")
        if self.ended_at <= self.started_at or self.recorded_at < self.ended_at:
            raise ValueError("pilot record times are invalid")
        if self.started_at.date() != self.service_date:
            raise ValueError("pilot start must match the UTC service date")
        if self.ended_at > datetime.combine(
            self.service_date + timedelta(days=1), datetime.min.time(), UTC
        ):
            raise ValueError("daily evidence cannot extend beyond the next UTC date")
        if (
            self.critical_passed > self.critical_total
            or self.noncritical_passed > self.noncritical_total
        ):
            raise ValueError("workflow passes cannot exceed totals")
        if self.record_sha256 != daily_record_sha256(self):
            raise ValueError("daily record hash is invalid")
        return self


class ShadowLedger(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    profile: ShadowPilotProfile
    records: tuple[ShadowDailyRecord, ...]
    ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_ledger(self) -> Self:
        for index, record in enumerate(self.records):
            expected = None if index == 0 else self.records[index - 1].record_sha256
            if record.previous_record_sha256 != expected:
                raise ValueError("daily record hash chain is invalid")
        if self.ledger_sha256 != shadow_ledger_sha256(self):
            raise ValueError("shadow ledger hash is invalid")
        return self


class ExpertPilotReview(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expert_id: str = Field(min_length=1, max_length=128)
    qualification_id: str = Field(min_length=1, max_length=128)
    rubric_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted: bool
    reviewed_at: datetime
    evidence_uri: str = Field(min_length=1, max_length=1024)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_time(self) -> Self:
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() != timedelta(0):
            raise ValueError("expert review time must use UTC")
        return self


class PilotStatus(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class PilotAssessment(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    status: PilotStatus
    completed_days: int = Field(ge=0, le=7)
    elapsed_hours: float = Field(ge=0)
    accepted_experts: int = Field(ge=0)
    reason_code: str
    next_action: str


def daily_record_sha256(record: ShadowDailyRecord) -> str:
    payload = record.model_dump(mode="json", exclude={"record_sha256"})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def build_daily_record(**values: object) -> ShadowDailyRecord:
    payload: dict[str, Any] = dict(values)
    provisional = ShadowDailyRecord.model_construct(**payload, record_sha256="0" * 64)
    return ShadowDailyRecord.model_validate(
        {**payload, "record_sha256": daily_record_sha256(provisional)}
    )


def shadow_ledger_sha256(ledger: ShadowLedger) -> str:
    payload = ledger.model_dump(mode="json", exclude={"ledger_sha256"})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def build_shadow_ledger(
    profile: ShadowPilotProfile, records: tuple[ShadowDailyRecord, ...]
) -> ShadowLedger:
    provisional = ShadowLedger.model_construct(
        profile=profile, records=records, ledger_sha256="0" * 64
    )
    return ShadowLedger(
        profile=profile,
        records=records,
        ledger_sha256=shadow_ledger_sha256(provisional),
    )


def assess_shadow_pilot(
    ledger: ShadowLedger,
    expert_reviews: tuple[ExpertPilotReview, ...],
    *,
    evaluated_at: datetime,
) -> PilotAssessment:
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() != timedelta(0):
        raise ValueError("pilot evaluation time must use UTC")
    records = ledger.records
    if len(records) < ledger.profile.required_days:
        return _assessment(
            PilotStatus.BLOCKED,
            len(records),
            0,
            0,
            "PILOT_DAYS_INCOMPLETE",
            "Continue the live shadow run until seven consecutive UTC dates are recorded.",
        )
    if len(records) != ledger.profile.required_days:
        return _assessment(
            PilotStatus.FAILED,
            7,
            0,
            0,
            "PILOT_RECORD_SET_INVALID",
            "Use exactly seven daily records for one candidate ledger.",
        )
    dates = tuple(record.service_date for record in records)
    if len(set(dates)) != len(dates) or any(
        current != dates[0] + timedelta(days=index) for index, current in enumerate(dates)
    ):
        return _assessment(
            PilotStatus.FAILED,
            7,
            0,
            0,
            "PILOT_DATES_INVALID",
            "Record seven unique consecutive UTC service dates.",
        )
    first = records[0]
    bindings = (
        first.build_sha256,
        first.assurance_sha256,
        first.performance_profile_sha256,
        first.budget_profile_sha256,
        first.configuration_sha256,
        first.workload_sha256,
        first.environment_id,
    )
    for record in records:
        current = (
            record.build_sha256,
            record.assurance_sha256,
            record.performance_profile_sha256,
            record.budget_profile_sha256,
            record.configuration_sha256,
            record.workload_sha256,
            record.environment_id,
        )
        if current != bindings:
            return _assessment(
                PilotStatus.FAILED,
                7,
                0,
                0,
                "PILOT_BINDING_CHANGED",
                "Restart the candidate after any build, profile, configuration, workload, or "
                "environment change.",
            )
        unsafe = (
            not record.environment_approved
            or not record.immutable_build
            or record.evidence_class is not PilotEvidenceClass.LIVE
            or any(
                state is not DailyGateState.PASS
                for state in (
                    record.security_state,
                    record.resilience_state,
                    record.performance_state,
                    record.token_state,
                )
            )
            or record.p0_findings
            or record.p1_findings
            or record.tenant_leaks
            or record.duplicate_committed_side_effects
            or record.correctness_failures
            or record.isolation_failures
            or record.critical_passed / record.critical_total < ledger.profile.critical_pass_rate
            or record.noncritical_passed / record.noncritical_total
            < ledger.profile.noncritical_pass_rate
        )
        if unsafe:
            return _assessment(
                PilotStatus.FAILED,
                7,
                0,
                0,
                "PILOT_DAILY_GATE_FAILED",
                "Correct or restart after the unsafe record for "
                f"{record.service_date.isoformat()}.",
            )
        if record.recorded_at > evaluated_at or record.ended_at > evaluated_at:
            return _assessment(
                PilotStatus.FAILED,
                7,
                0,
                0,
                "PILOT_FUTURE_RECORD",
                "Remove future evidence and wait for real service time.",
            )
    elapsed_hours = (evaluated_at - first.started_at).total_seconds() / 3600
    if elapsed_hours < ledger.profile.minimum_elapsed_hours:
        return _assessment(
            PilotStatus.BLOCKED,
            7,
            elapsed_hours,
            0,
            "PILOT_ELAPSED_TIME_LOW",
            "Wait until at least six full 24-hour periods have elapsed.",
        )
    if len({review.expert_id for review in expert_reviews}) != len(expert_reviews):
        return _assessment(
            PilotStatus.FAILED,
            7,
            elapsed_hours,
            0,
            "PILOT_EXPERT_SET_INVALID",
            "Provide distinct expert identities.",
        )
    accepted = sum(
        review.accepted and review.ledger_sha256 == ledger.ledger_sha256
        for review in expert_reviews
    )
    invalid_review = any(
        review.ledger_sha256 != ledger.ledger_sha256
        or not review.accepted
        or review.reviewed_at > evaluated_at
        or review.reviewed_at < records[-1].ended_at
        for review in expert_reviews
    )
    if invalid_review:
        return _assessment(
            PilotStatus.FAILED,
            7,
            elapsed_hours,
            accepted,
            "PILOT_EXPERT_REVIEW_INVALID",
            "Repeat expert review against the exact completed ledger.",
        )
    if accepted < ledger.profile.required_expert_reviews:
        return _assessment(
            PilotStatus.BLOCKED,
            7,
            elapsed_hours,
            accepted,
            "PILOT_EXPERT_REVIEWS_MISSING",
            "Obtain the required distinct qualified expert acceptances.",
        )
    return _assessment(
        PilotStatus.PASS,
        7,
        elapsed_hours,
        accepted,
        "PILOT_ACCEPTED",
        "Preserve the exact ledger and expert evidence for release-candidate construction.",
    )


def _assessment(
    status: PilotStatus,
    days: int,
    elapsed: float,
    experts: int,
    reason: str,
    action: str,
) -> PilotAssessment:
    return PilotAssessment(
        status=status,
        completed_days=days,
        elapsed_hours=max(elapsed, 0),
        accepted_experts=experts,
        reason_code=reason,
        next_action=action,
    )
