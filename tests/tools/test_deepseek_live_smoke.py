"""Offline checks for the explicitly gated DeepSeek live-smoke harness."""

from ndt_agents.models.profiles import ModelRuntimeKind
from tools.deepseek_live_smoke import OUTPUT_SCHEMA, _profile, _sanitized_failure


def test_live_smoke_profile_is_hosted_synthetic_and_strict() -> None:
    profile = _profile()

    assert profile.runtime.kind is ModelRuntimeKind.HOSTED_API
    assert profile.runtime.network_required
    assert not profile.runtime.deterministic
    assert profile.output_schema == OUTPUT_SCHEMA
    assert tuple(item.metric for item in profile.thresholds) == ("quality_score",)
    assert profile.report_eligibility.value == "PRELIMINARY_REVIEW"


def test_acknowledgement_denial_report_is_sanitized_and_zero_call() -> None:
    report = _sanitized_failure("DEEPSEEK_POLICY_ACKNOWLEDGEMENT_REQUIRED")

    assert report == {
        "result": "FAILED",
        "failure_code": "DEEPSEEK_POLICY_ACKNOWLEDGEMENT_REQUIRED",
        "physical_network_calls": 0,
        "secret_output": False,
    }
