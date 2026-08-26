"""S6-08 shadow-run ledger and expert-pilot tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from ndt_agents.operations.pilot import (
    DailyGateState,
    ExpertPilotReview,
    PilotEvidenceClass,
    PilotStatus,
    ShadowDailyRecord,
    ShadowPilotProfile,
    assess_shadow_pilot,
    build_daily_record,
    build_shadow_ledger,
)

HASHES = tuple(character * 64 for character in "abcdef")
RUBRIC = "1" * 64


def records(**updates: object) -> tuple[ShadowDailyRecord, ...]:
    result: list[ShadowDailyRecord] = []
    previous = None
    start_date = date(2026, 8, 1)
    for index in range(7):
        service_date = start_date + timedelta(days=index)
        started = datetime.combine(service_date, datetime.min.time(), UTC) + timedelta(hours=1)
        values: dict[str, object] = {
            "service_date": service_date,
            "started_at": started,
            "ended_at": started + timedelta(hours=22),
            "recorded_at": started + timedelta(hours=22, minutes=5),
            "build_sha256": HASHES[0],
            "assurance_sha256": HASHES[1],
            "performance_profile_sha256": HASHES[2],
            "budget_profile_sha256": HASHES[3],
            "configuration_sha256": HASHES[4],
            "workload_sha256": HASHES[5],
            "environment_id": "production-like-pilot-1",
            "environment_approved": True,
            "immutable_build": True,
            "evidence_class": PilotEvidenceClass.LIVE,
            "task_count": 100,
            "expert_visible_cases": 10,
            "critical_total": 20,
            "critical_passed": 20,
            "noncritical_total": 100,
            "noncritical_passed": 99,
            "security_state": DailyGateState.PASS,
            "resilience_state": DailyGateState.PASS,
            "performance_state": DailyGateState.PASS,
            "token_state": DailyGateState.PASS,
            "p0_findings": 0,
            "p1_findings": 0,
            "tenant_leaks": 0,
            "duplicate_committed_side_effects": 0,
            "correctness_failures": 0,
            "isolation_failures": 0,
            "evidence_uri": f"artifact://pilot/day-{index + 1}",
            "evidence_sha256": f"{index + 2:x}" * 64,
            "previous_record_sha256": previous,
        }
        if index == 0:
            values.update(updates)
        record = build_daily_record(**values)
        result.append(record)
        previous = record.record_sha256
    return tuple(result)


def reviews(ledger_sha256: str, reviewed_at: datetime) -> tuple[ExpertPilotReview, ...]:
    return tuple(
        ExpertPilotReview(
            ledger_sha256=ledger_sha256,
            expert_id=f"expert-{index}",
            qualification_id=f"qualification-{index}",
            rubric_sha256=RUBRIC,
            accepted=True,
            reviewed_at=reviewed_at,
            evidence_uri=f"artifact://pilot/expert-{index}",
            evidence_sha256=f"{index + 8:x}" * 64,
        )
        for index in range(2)
    )


def test_seven_live_days_and_two_experts_pass_contract() -> None:
    ledger = build_shadow_ledger(ShadowPilotProfile(), records())
    evaluated_at = datetime(2026, 8, 8, 1, tzinfo=UTC)
    result = assess_shadow_pilot(
        ledger,
        reviews(ledger.ledger_sha256, datetime(2026, 8, 8, 0, tzinfo=UTC)),
        evaluated_at=evaluated_at,
    )
    assert result.status is PilotStatus.PASS
    assert result.completed_days == 7
    assert result.elapsed_hours >= 144
    assert result.accepted_experts == 2


def test_incomplete_run_and_missing_experts_are_blocked() -> None:
    complete = records()
    short = build_shadow_ledger(ShadowPilotProfile(), complete[:1])
    assert (
        assess_shadow_pilot(short, (), evaluated_at=datetime(2026, 8, 2, tzinfo=UTC)).reason_code
        == "PILOT_DAYS_INCOMPLETE"
    )
    ledger = build_shadow_ledger(ShadowPilotProfile(), complete)
    missing = assess_shadow_pilot(ledger, (), evaluated_at=datetime(2026, 8, 8, 1, tzinfo=UTC))
    assert missing.status is PilotStatus.BLOCKED
    assert missing.reason_code == "PILOT_EXPERT_REVIEWS_MISSING"


@pytest.mark.parametrize(
    "updates",
    [
        {"evidence_class": PilotEvidenceClass.SYNTHETIC},
        {"environment_approved": False},
        {"tenant_leaks": 1},
        {"duplicate_committed_side_effects": 1},
        {"critical_passed": 19},
        {"noncritical_passed": 97},
        {"security_state": DailyGateState.FAILED},
    ],
)
def test_daily_safety_and_quality_fail_closed(updates: dict[str, object]) -> None:
    ledger = build_shadow_ledger(ShadowPilotProfile(), records(**updates))
    result = assess_shadow_pilot(ledger, (), evaluated_at=datetime(2026, 8, 8, 1, tzinfo=UTC))
    assert result.status is PilotStatus.FAILED
    assert result.reason_code == "PILOT_DAILY_GATE_FAILED"


def test_changed_binding_and_future_record_fail() -> None:
    items = list(records())
    second = items[1].model_dump(exclude={"record_sha256"})
    second["build_sha256"] = "9" * 64
    second["previous_record_sha256"] = items[0].record_sha256
    items[1] = build_daily_record(**second)
    for index in range(2, len(items)):
        values = items[index].model_dump(exclude={"record_sha256"})
        values["previous_record_sha256"] = items[index - 1].record_sha256
        items[index] = build_daily_record(**values)
    ledger = build_shadow_ledger(ShadowPilotProfile(), tuple(items))
    changed = assess_shadow_pilot(ledger, (), evaluated_at=datetime(2026, 8, 8, 1, tzinfo=UTC))
    assert changed.reason_code == "PILOT_BINDING_CHANGED"

    normal = build_shadow_ledger(ShadowPilotProfile(), records())
    future = assess_shadow_pilot(normal, (), evaluated_at=datetime(2026, 8, 7, 12, tzinfo=UTC))
    assert future.reason_code == "PILOT_FUTURE_RECORD"


def test_broken_chain_and_invalid_expert_binding_fail() -> None:
    items = records()
    broken = items[1].model_copy(update={"previous_record_sha256": "0" * 64})
    with pytest.raises(ValidationError):
        build_shadow_ledger(ShadowPilotProfile(), (items[0], broken, *items[2:]))

    ledger = build_shadow_ledger(ShadowPilotProfile(), items)
    invalid = reviews("0" * 64, datetime(2026, 8, 8, tzinfo=UTC))
    result = assess_shadow_pilot(ledger, invalid, evaluated_at=datetime(2026, 8, 8, 1, tzinfo=UTC))
    assert result.reason_code == "PILOT_EXPERT_REVIEW_INVALID"
