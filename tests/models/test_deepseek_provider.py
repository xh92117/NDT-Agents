"""S5-07-LIVE strict DeepSeek transport and adapter tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

import pytest
from pydantic import SecretStr

from ndt_agents.models.deepseek import (
    DEEPSEEK_ENDPOINT_URL,
    DeepSeekHttpResponse,
    DeepSeekModelInferenceProvider,
    UrllibDeepSeekHttpTransport,
)
from ndt_agents.models.inference import (
    MODEL_INFERENCE_CONTRACT_VERSION,
    CanonicalPromptMode,
    ModelProviderError,
    ModelProviderRequest,
    ModelProviderStatus,
    ModelReasoningMode,
    model_provider_request_sha256,
)
from ndt_agents.models.registry import ApiProtocol, canonical_sha256
from ndt_agents.security.models import SecretRef, SecretSelector, SecurityEnvironment
from tests.models.test_model_inference import OUTPUT_SCHEMA, dataset


class RecordingSecrets:
    def __init__(self, selector: SecretSelector, value: str = "unit-deepseek-secret") -> None:
        self.selector = selector
        self.ref = SecretRef(**selector.model_dump(), version="test-v1")
        self.value = value
        self.current_calls = 0
        self.reveal_calls = 0

    def current_ref(self, selector: SecretSelector) -> SecretRef:
        self.current_calls += 1
        assert selector == self.selector
        return self.ref

    def reveal(self, ref: SecretRef) -> SecretStr:
        self.reveal_calls += 1
        assert ref == self.ref
        return SecretStr(self.value)

    def rotate(
        self,
        selector: SecretSelector,
        version: str,
        value: SecretStr,
    ) -> SecretRef:
        del selector, version, value
        raise AssertionError("test secret provider is read-only")

    def revoke(self, ref: SecretRef) -> None:
        del ref
        raise AssertionError("test secret provider is read-only")


class RecordingTransport:
    def __init__(self, response: DeepSeekHttpResponse) -> None:
        self.response = response
        self.calls = 0
        self.url: str | None = None
        self.headers: dict[str, str] = {}
        self.body = b""
        self.timeout_seconds = 0.0

    async def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> DeepSeekHttpResponse:
        self.calls += 1
        self.url = url
        self.headers = dict(headers)
        self.body = body
        self.timeout_seconds = timeout_seconds
        return self.response


def selector() -> SecretSelector:
    return SecretSelector(
        secret_id="deepseek-api-key",
        environment=SecurityEnvironment.LOCAL,
        tenant_id=UUID("00000000-0000-4000-8000-000000000101"),
        project_id=UUID("00000000-0000-4000-8000-000000000102"),
        purpose="model.deepseek.credential",
    )


def request(**updates: object) -> ModelProviderRequest:
    payload: dict[str, object] = {
        "schema_version": MODEL_INFERENCE_CONTRACT_VERSION,
        "call_id": UUID("00000000-0000-4000-8000-000000000401"),
        "request_sha256": "1" * 64,
        "profile_sha256": "2" * 64,
        "provider_id": "deepseek",
        "provider_version": "1.0.0",
        "endpoint_id": "openai-chat",
        "endpoint_url": DEEPSEEK_ENDPOINT_URL,
        "protocol": ApiProtocol.OPENAI_CHAT_COMPLETIONS,
        "model_id": "deepseek-v4-pro",
        "model_snapshot": "DeepSeek-V4-Pro-0813",
        "secret_selector": selector(),
        "canonical_data": dataset(),
        "instruction_id": "ut-indication-classifier",
        "instruction_version": "1.0.0",
        "instruction_text": "Return a bounded NDT classification using the supplied contract.",
        "output_schema_id": "ut-model-output@1.0.0",
        "output_schema": OUTPUT_SCHEMA,
        "output_schema_sha256": canonical_sha256(OUTPUT_SCHEMA),
        "required_metrics": ("quality_score",),
        "parameters": {"temperature": "0"},
        "maximum_input_tokens": 100,
        "maximum_output_tokens": 100,
    }
    payload.update(updates)
    draft = ModelProviderRequest.model_construct(
        **payload,  # type: ignore[arg-type]
        provider_request_sha256="0" * 64,
    )
    return ModelProviderRequest.model_validate(
        {
            **payload,
            "provider_request_sha256": model_provider_request_sha256(draft),
        }
    )


def response(
    *,
    status_code: int = 200,
    model: str = "deepseek-v4-pro",
    finish_reason: str = "stop",
    content: object | None = None,
) -> DeepSeekHttpResponse:
    if content is None:
        content = {
            "output": {
                "classification": "NO_INDICATION",
                "summary": "Synthetic offline response.",
            },
            "confidence": 0.97,
            "metrics": {"quality_score": 0.96},
        }
    body = {
        "id": "chatcmpl-test-1",
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(content, separators=(",", ":")),
                },
            }
        ],
        "usage": {"prompt_tokens": 60, "completion_tokens": 40, "total_tokens": 100},
    }
    return DeepSeekHttpResponse(
        status_code=status_code,
        body=json.dumps(body, separators=(",", ":")).encode(),
    )


def provider_result(
    provider: DeepSeekModelInferenceProvider,
    provider_request: ModelProviderRequest,
) -> Any:
    return asyncio.run(provider.infer(provider_request))


def test_success_uses_exact_route_prompt_contract_json_mode_and_one_call() -> None:
    provider_request = request()
    secrets = RecordingSecrets(provider_request.secret_selector)
    transport = RecordingTransport(response())
    provider = DeepSeekModelInferenceProvider(
        secrets,
        transport=transport,
        timeout_seconds=9.0,
    )

    reply = provider_result(provider, provider_request)

    assert reply.status is ModelProviderStatus.SUCCESS
    assert reply.output["classification"] == "NO_INDICATION"
    assert str(reply.confidence) == "0.97"
    assert tuple(item.metric for item in reply.metrics) == ("quality_score",)
    assert reply.input_tokens == 60 and reply.output_tokens == 40
    assert reply.physical_network_calls == 1
    assert secrets.current_calls == secrets.reveal_calls == transport.calls == 1
    assert transport.url == DEEPSEEK_ENDPOINT_URL
    assert transport.timeout_seconds == 9.0
    assert transport.headers["Authorization"] == f"Bearer {secrets.value}"
    payload = json.loads(transport.body)
    assert payload["model"] == provider_request.model_id
    assert payload["stream"] is False
    assert payload["response_format"] == {"type": "json_object"}
    assert "thinking" not in payload
    assert payload["messages"][0] == {
        "role": "system",
        "content": provider_request.instruction_text,
    }
    user_payload = json.loads(payload["messages"][1]["content"])
    assert "topology" in user_payload["canonical_data"]
    assert user_payload["response_contract"]["output_schema_sha256"] == (
        provider_request.output_schema_sha256
    )
    assert secrets.value.encode() not in transport.body


def test_identity_only_prompt_projection_retains_binding_without_raw_dataset() -> None:
    provider_request = request(canonical_prompt_mode=CanonicalPromptMode.IDENTITY_ONLY)
    secrets = RecordingSecrets(provider_request.secret_selector)
    transport = RecordingTransport(response())
    provider = DeepSeekModelInferenceProvider(secrets, transport=transport)

    reply = provider_result(provider, provider_request)

    assert reply.status is ModelProviderStatus.SUCCESS
    payload = json.loads(transport.body)
    user_payload = json.loads(payload["messages"][1]["content"])
    canonical = user_payload["canonical_data"]
    assert set(canonical) == {
        "dataset_id",
        "manifest_sha256",
        "method_code",
        "origin",
        "schema_version",
        "scope",
    }
    assert canonical["dataset_id"] == str(provider_request.canonical_data.dataset_id)
    assert canonical["manifest_sha256"] == provider_request.canonical_data.manifest_sha256
    assert canonical["scope"] == provider_request.canonical_data.scope.model_dump(mode="json")
    assert "topology" not in canonical
    assert "source" not in canonical
    assert "channels" not in canonical


def test_disabled_reasoning_emits_exact_thinking_off_control() -> None:
    provider_request = request(reasoning_mode=ModelReasoningMode.DISABLED)
    secrets = RecordingSecrets(provider_request.secret_selector)
    transport = RecordingTransport(response())
    provider = DeepSeekModelInferenceProvider(secrets, transport=transport)

    reply = provider_result(provider, provider_request)

    assert reply.status is ModelProviderStatus.SUCCESS
    payload = json.loads(transport.body)
    assert payload["thinking"] == {"type": "disabled"}


@pytest.mark.parametrize(
    "updates",
    (
        {"provider_id": "other"},
        {"provider_version": "2.0.0"},
        {"endpoint_id": "other"},
        {"endpoint_url": "https://api.deepseek.com/other"},
        {"endpoint_url": "https://api.deepseek.com:444/chat/completions"},
        {"protocol": ApiProtocol.OPENAI_RESPONSES},
        {"model_id": "unknown-model"},
        {"secret_selector": selector().model_copy(update={"purpose": "model.other"})},
    ),
)
def test_route_denial_happens_before_secret_or_network(updates: dict[str, object]) -> None:
    provider_request = request(**updates)
    secrets = RecordingSecrets(provider_request.secret_selector)
    transport = RecordingTransport(response())
    provider = DeepSeekModelInferenceProvider(secrets, transport=transport)

    with pytest.raises(ModelProviderError) as raised:
        provider_result(provider, provider_request)

    assert raised.value.code == "MODEL_PROVIDER_ROUTE_INVALID"
    assert raised.value.physical_network_calls == 0
    assert secrets.current_calls == secrets.reveal_calls == transport.calls == 0


@pytest.mark.parametrize(
    ("status_code", "code", "retryable"),
    (
        (400, "MODEL_PROVIDER_REQUEST_INVALID", False),
        (401, "MODEL_PROVIDER_AUTHENTICATION_FAILED", False),
        (402, "MODEL_PROVIDER_BALANCE_EXHAUSTED", False),
        (422, "MODEL_PROVIDER_REQUEST_INVALID", False),
        (429, "MODEL_RATE_LIMITED", True),
        (500, "MODEL_PROVIDER_UNAVAILABLE", True),
        (503, "MODEL_PROVIDER_UNAVAILABLE", True),
    ),
)
def test_official_http_errors_are_typed(
    status_code: int,
    code: str,
    retryable: bool,
) -> None:
    provider_request = request()
    secrets = RecordingSecrets(provider_request.secret_selector)
    transport = RecordingTransport(DeepSeekHttpResponse(status_code, b'{"error":"ignored"}'))
    provider = DeepSeekModelInferenceProvider(secrets, transport=transport)

    with pytest.raises(ModelProviderError) as raised:
        provider_result(provider, provider_request)

    assert raised.value.code == code
    assert raised.value.retryable is retryable
    assert raised.value.physical_network_calls == 1
    assert transport.calls == 1


@pytest.mark.parametrize(
    ("provider_response", "code"),
    (
        (DeepSeekHttpResponse(200, b"not-json"), "MODEL_PROVIDER_RESPONSE_INVALID"),
        (
            DeepSeekHttpResponse(200, b'{"id":"one","id":"two"}'),
            "MODEL_PROVIDER_RESPONSE_INVALID",
        ),
        (response(model="changed-model"), "MODEL_PROVIDER_IDENTITY_INVALID"),
        (
            response(content={"output": {}, "confidence": 0.9, "metrics": {}}),
            "MODEL_PROVIDER_RESPONSE_INVALID",
        ),
    ),
)
def test_malformed_or_unbound_success_is_rejected(
    provider_response: DeepSeekHttpResponse,
    code: str,
) -> None:
    provider_request = request()
    provider = DeepSeekModelInferenceProvider(
        RecordingSecrets(provider_request.secret_selector),
        transport=RecordingTransport(provider_response),
    )

    with pytest.raises(ModelProviderError) as raised:
        provider_result(provider, provider_request)

    assert raised.value.code == code
    assert raised.value.physical_network_calls == 1


@pytest.mark.parametrize(
    ("finish_reason", "status", "code", "retryable"),
    (
        ("length", ModelProviderStatus.INCOMPLETE, "MODEL_INCOMPLETE", False),
        ("content_filter", ModelProviderStatus.REFUSED, "MODEL_REFUSED", False),
        (
            "insufficient_system_resource",
            ModelProviderStatus.FAILED,
            "MODEL_PROVIDER_UNAVAILABLE",
            True,
        ),
    ),
)
def test_terminal_finish_reasons_preserve_typed_partial_or_failure(
    finish_reason: str,
    status: ModelProviderStatus,
    code: str,
    retryable: bool,
) -> None:
    provider_request = request()
    provider = DeepSeekModelInferenceProvider(
        RecordingSecrets(provider_request.secret_selector),
        transport=RecordingTransport(response(finish_reason=finish_reason)),
    )

    reply = provider_result(provider, provider_request)

    assert reply.status is status
    assert reply.error_code == code
    assert reply.retryable is retryable
    assert reply.output == {}
    assert reply.physical_network_calls == 1


def test_default_transport_rejects_any_non_exact_url_without_network() -> None:
    transport = UrllibDeepSeekHttpTransport()

    with pytest.raises(Exception) as raised:
        asyncio.run(
            transport.post_json(
                "http://api.deepseek.com/chat/completions",
                headers={"Content-Type": "application/json"},
                body=b"{}",
                timeout_seconds=1,
            )
        )

    assert "MODEL_PROVIDER_ROUTE_INVALID" in str(raised.value)
