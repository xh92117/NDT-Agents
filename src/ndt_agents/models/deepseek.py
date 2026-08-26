"""Strict one-call DeepSeek Chat Completions provider adapter."""

from __future__ import annotations

import asyncio
import json
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from http.client import HTTPResponse
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from ndt_agents.models.inference import (
    ModelMetric,
    ModelProviderError,
    ModelProviderReply,
    ModelProviderRequest,
    ModelProviderStatus,
)
from ndt_agents.models.registry import ApiProtocol
from ndt_agents.security.models import SecurityError
from ndt_agents.security.secrets import SecretProvider

DEEPSEEK_PROVIDER_ID = "deepseek"
DEEPSEEK_PROVIDER_VERSION = "1.0.0"
DEEPSEEK_ENDPOINT_ID = "openai-chat"
DEEPSEEK_ENDPOINT_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_CREDENTIAL_PURPOSE = "model.deepseek.credential"
DEEPSEEK_MODEL_IDS = frozenset(
    {"deepseek-v4-pro", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp"}
)

_MAX_REQUEST_BYTES = 2 * 1024 * 1024
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_JSON_DEPTH = 64


@dataclass(frozen=True, slots=True)
class DeepSeekHttpResponse:
    status_code: int
    body: bytes


class DeepSeekHttpTransport(Protocol):
    async def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> DeepSeekHttpResponse: ...


class DeepSeekConfiguredRuntime(Protocol):
    @property
    def secret_provider(self) -> SecretProvider: ...


class _DenyRedirects(HTTPRedirectHandler):
    def redirect_request(  # type: ignore[override]
        self,
        req: Request,
        fp: HTTPResponse,
        code: int,
        msg: str,
        headers: Mapping[str, str],
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


class _TransportFailure(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class UrllibDeepSeekHttpTransport:
    """TLS-validating, redirect-denying, bounded stdlib HTTPS transport."""

    async def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> DeepSeekHttpResponse:
        _validate_endpoint(url)
        if len(body) > _MAX_REQUEST_BYTES:
            raise _TransportFailure("MODEL_PROVIDER_REQUEST_TOO_LARGE", retryable=False)
        if timeout_seconds <= 0:
            raise _TransportFailure("MODEL_PROVIDER_TIMEOUT_INVALID", retryable=False)
        return await asyncio.to_thread(
            self._post_sync,
            url,
            dict(headers),
            body,
            timeout_seconds,
        )

    @staticmethod
    def _post_sync(
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> DeepSeekHttpResponse:
        request = Request(url, data=body, headers=headers, method="POST")
        opener = build_opener(
            HTTPSHandler(context=ssl.create_default_context()),
            _DenyRedirects(),
        )
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                return DeepSeekHttpResponse(
                    status_code=response.status,
                    body=_read_bounded(response),
                )
        except HTTPError as error:
            try:
                body_value = _read_bounded(error)
            finally:
                error.close()
            return DeepSeekHttpResponse(status_code=error.code, body=body_value)
        except TimeoutError:
            raise _TransportFailure("MODEL_PROVIDER_TIMEOUT", retryable=True) from None
        except ssl.SSLError:
            raise _TransportFailure("MODEL_PROVIDER_TLS_FAILED", retryable=False) from None
        except URLError as error:
            reason = error.reason
            if isinstance(reason, ssl.SSLError):
                code, retryable = "MODEL_PROVIDER_TLS_FAILED", False
            elif isinstance(reason, TimeoutError):
                code, retryable = "MODEL_PROVIDER_TIMEOUT", True
            else:
                code, retryable = "MODEL_PROVIDER_NETWORK_FAILED", True
            raise _TransportFailure(code, retryable=retryable) from None
        except OSError:
            raise _TransportFailure("MODEL_PROVIDER_NETWORK_FAILED", retryable=True) from None


class DeepSeekModelInferenceProvider:
    """Map one authorized provider request to one non-streaming DeepSeek call."""

    def __init__(
        self,
        secret_provider: SecretProvider,
        *,
        transport: DeepSeekHttpTransport | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 3_600:
            raise ValueError("DeepSeek timeout must be within (0, 3600] seconds")
        self._secrets = secret_provider
        self._transport = transport or UrllibDeepSeekHttpTransport()
        self._timeout_seconds = timeout_seconds

    async def infer(self, request: ModelProviderRequest) -> ModelProviderReply:
        _validate_request(request)
        payload = _request_payload(request)
        body = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(body) > _MAX_REQUEST_BYTES:
            raise _provider_error(
                "MODEL_PROVIDER_REQUEST_TOO_LARGE",
                retryable=False,
                network_calls=0,
            )

        try:
            ref = self._secrets.current_ref(request.secret_selector)
            secret = self._secrets.reveal(ref).get_secret_value()
            if not 1 <= len(secret) <= 16_384:
                raise ValueError("invalid secret length")
        except (SecurityError, ValueError):
            raise _provider_error(
                "MODEL_PROVIDER_SECRET_UNAVAILABLE",
                retryable=False,
                network_calls=0,
            ) from None

        try:
            response = await self._transport.post_json(
                request.endpoint_url,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {secret}",
                    "Content-Type": "application/json",
                },
                body=body,
                timeout_seconds=self._timeout_seconds,
            )
        except _TransportFailure as error:
            raise _provider_error(
                error.code,
                retryable=error.retryable,
                network_calls=1,
            ) from None
        finally:
            secret = ""

        if response.status_code != 200:
            code, retryable = _http_error(response.status_code)
            raise _provider_error(code, retryable=retryable, network_calls=1)
        return _parse_success(request, response.body)


def build_deepseek_provider(
    runtime: DeepSeekConfiguredRuntime,
    *,
    transport: DeepSeekHttpTransport | None = None,
    timeout_seconds: float = 120.0,
) -> DeepSeekModelInferenceProvider:
    """Build the opt-in adapter from a configured runtime without revealing its secret."""

    return DeepSeekModelInferenceProvider(
        runtime.secret_provider,
        transport=transport,
        timeout_seconds=timeout_seconds,
    )


def _validate_request(request: ModelProviderRequest) -> None:
    if (
        request.provider_id != DEEPSEEK_PROVIDER_ID
        or request.provider_version != DEEPSEEK_PROVIDER_VERSION
        or request.endpoint_id != DEEPSEEK_ENDPOINT_ID
        or request.protocol is not ApiProtocol.OPENAI_CHAT_COMPLETIONS
        or request.model_id not in DEEPSEEK_MODEL_IDS
        or request.secret_selector.purpose != DEEPSEEK_CREDENTIAL_PURPOSE
    ):
        raise _provider_error("MODEL_PROVIDER_ROUTE_INVALID", retryable=False, network_calls=0)
    try:
        _validate_endpoint(request.endpoint_url)
    except _TransportFailure:
        raise _provider_error(
            "MODEL_PROVIDER_ROUTE_INVALID", retryable=False, network_calls=0
        ) from None


def _validate_endpoint(url: str) -> None:
    parsed = urlsplit(url)
    if (
        url != DEEPSEEK_ENDPOINT_URL
        or parsed.scheme != "https"
        or parsed.hostname != "api.deepseek.com"
        or parsed.port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/chat/completions"
        or parsed.query
        or parsed.fragment
    ):
        raise _TransportFailure("MODEL_PROVIDER_ROUTE_INVALID", retryable=False)


def _request_payload(request: ModelProviderRequest) -> dict[str, object]:
    response_contract = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "output": request.output_schema,
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "metrics": {
                "type": "object",
                "additionalProperties": False,
                "properties": {metric: {"type": "number"} for metric in request.required_metrics},
                "required": list(request.required_metrics),
            },
        },
        "required": ["output", "confidence", "metrics"],
    }
    user_content = {
        "canonical_data": request.canonical_data.model_dump(mode="json"),
        "parameters": request.parameters,
        "response_contract": {
            "output_schema_id": request.output_schema_id,
            "output_schema_sha256": request.output_schema_sha256,
            "json_schema": response_contract,
        },
    }
    return {
        "max_tokens": request.maximum_output_tokens,
        "messages": [
            {"role": "system", "content": request.instruction_text},
            {
                "role": "user",
                "content": json.dumps(
                    user_content,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            },
        ],
        "model": request.model_id,
        "response_format": {"type": "json_object"},
        "stream": False,
        "temperature": 0,
    }


def _parse_success(request: ModelProviderRequest, body: bytes) -> ModelProviderReply:
    payload = _load_json_object(body)
    provider_request_id = _bounded_text(payload.get("id"), maximum=256)
    model = _bounded_text(payload.get("model"), maximum=128)
    if model != request.model_id:
        raise _provider_error("MODEL_PROVIDER_IDENTITY_INVALID", retryable=False, network_calls=1)
    choices = payload.get("choices")
    usage = payload.get("usage")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(usage, dict):
        raise _provider_error("MODEL_PROVIDER_RESPONSE_INVALID", retryable=False, network_calls=1)
    choice = choices[0]
    if not isinstance(choice, dict) or choice.get("index") not in {0, None}:
        raise _provider_error("MODEL_PROVIDER_RESPONSE_INVALID", retryable=False, network_calls=1)
    finish_reason = _bounded_text(choice.get("finish_reason"), maximum=256)
    input_tokens = _usage_integer(usage, "prompt_tokens")
    output_tokens = _usage_integer(usage, "completion_tokens")
    if finish_reason != "stop":
        return _terminal_reply(
            request,
            provider_request_id,
            input_tokens,
            output_tokens,
            finish_reason,
        )
    message = choice.get("message")
    if not isinstance(message, dict):
        raise _provider_error("MODEL_PROVIDER_RESPONSE_INVALID", retryable=False, network_calls=1)
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise _provider_error("MODEL_PROVIDER_RESPONSE_INVALID", retryable=False, network_calls=1)
    envelope = _load_json_object(content.encode("utf-8"))
    if set(envelope) != {"output", "confidence", "metrics"}:
        raise _provider_error("MODEL_PROVIDER_RESPONSE_INVALID", retryable=False, network_calls=1)
    output = envelope["output"]
    raw_metrics = envelope["metrics"]
    if not isinstance(output, dict) or not isinstance(raw_metrics, dict):
        raise _provider_error("MODEL_PROVIDER_RESPONSE_INVALID", retryable=False, network_calls=1)
    if tuple(sorted(raw_metrics)) != request.required_metrics:
        raise _provider_error("MODEL_PROVIDER_RESPONSE_INVALID", retryable=False, network_calls=1)
    confidence = _decimal(envelope["confidence"])
    if confidence < 0 or confidence > 1:
        raise _provider_error("MODEL_PROVIDER_RESPONSE_INVALID", retryable=False, network_calls=1)
    metrics = tuple(
        ModelMetric(metric=metric, value=_decimal(raw_metrics[metric]))
        for metric in request.required_metrics
    )
    return ModelProviderReply(
        call_id=request.call_id,
        provider_request_sha256=request.provider_request_sha256,
        provider_id=request.provider_id,
        provider_version=request.provider_version,
        endpoint_id=request.endpoint_id,
        model_id=request.model_id,
        model_snapshot=request.model_snapshot,
        provider_request_id=provider_request_id,
        status=ModelProviderStatus.SUCCESS,
        output=output,
        artifacts=(),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        confidence=confidence,
        metrics=metrics,
        finish_reason=finish_reason,
        physical_network_calls=1,
    )


def _terminal_reply(
    request: ModelProviderRequest,
    provider_request_id: str,
    input_tokens: int,
    output_tokens: int,
    finish_reason: str,
) -> ModelProviderReply:
    if finish_reason == "length":
        status, code, retryable = ModelProviderStatus.INCOMPLETE, "MODEL_INCOMPLETE", False
    elif finish_reason == "content_filter":
        status, code, retryable = ModelProviderStatus.REFUSED, "MODEL_REFUSED", False
    elif finish_reason == "insufficient_system_resource":
        status, code, retryable = (
            ModelProviderStatus.FAILED,
            "MODEL_PROVIDER_UNAVAILABLE",
            True,
        )
    else:
        raise _provider_error("MODEL_PROVIDER_RESPONSE_INVALID", retryable=False, network_calls=1)
    return ModelProviderReply(
        call_id=request.call_id,
        provider_request_sha256=request.provider_request_sha256,
        provider_id=request.provider_id,
        provider_version=request.provider_version,
        endpoint_id=request.endpoint_id,
        model_id=request.model_id,
        model_snapshot=request.model_snapshot,
        provider_request_id=provider_request_id,
        status=status,
        output={},
        artifacts=(),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        confidence=None,
        metrics=(),
        finish_reason=finish_reason,
        physical_network_calls=1,
        error_code=code,
        error_impact="No validated model output is available.",
        next_action="Review the provider state before authorizing a new call.",
        retryable=retryable,
    )


def _load_json_object(raw: bytes) -> dict[str, Any]:
    if len(raw) > _MAX_RESPONSE_BYTES or raw.startswith(b"\xef\xbb\xbf"):
        raise _provider_error("MODEL_PROVIDER_RESPONSE_INVALID", retryable=False, network_calls=1)
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_float=Decimal,
            parse_constant=_reject_non_finite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise _provider_error(
            "MODEL_PROVIDER_RESPONSE_INVALID", retryable=False, network_calls=1
        ) from None
    if not isinstance(value, dict) or _json_depth(value) > _MAX_JSON_DEPTH:
        raise _provider_error("MODEL_PROVIDER_RESPONSE_INVALID", retryable=False, network_calls=1)
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _json_depth(value: object, depth: int = 1) -> int:
    if isinstance(value, dict):
        return max((depth, *(_json_depth(item, depth + 1) for item in value.values())))
    if isinstance(value, list):
        return max((depth, *(_json_depth(item, depth + 1) for item in value)))
    return depth


def _decimal(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, str)):
        raise _provider_error("MODEL_PROVIDER_RESPONSE_INVALID", retryable=False, network_calls=1)
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise _provider_error(
            "MODEL_PROVIDER_RESPONSE_INVALID", retryable=False, network_calls=1
        ) from None
    if not result.is_finite():
        raise _provider_error("MODEL_PROVIDER_RESPONSE_INVALID", retryable=False, network_calls=1)
    return result


def _usage_integer(usage: dict[str, Any], key: str) -> int:
    value = usage.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10_000_000:
        raise _provider_error("MODEL_PROVIDER_RESPONSE_INVALID", retryable=False, network_calls=1)
    return value


def _bounded_text(value: object, *, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise _provider_error("MODEL_PROVIDER_RESPONSE_INVALID", retryable=False, network_calls=1)
    return value


def _http_error(status_code: int) -> tuple[str, bool]:
    return {
        400: ("MODEL_PROVIDER_REQUEST_INVALID", False),
        401: ("MODEL_PROVIDER_AUTHENTICATION_FAILED", False),
        402: ("MODEL_PROVIDER_BALANCE_EXHAUSTED", False),
        422: ("MODEL_PROVIDER_REQUEST_INVALID", False),
        429: ("MODEL_RATE_LIMITED", True),
        500: ("MODEL_PROVIDER_UNAVAILABLE", True),
        503: ("MODEL_PROVIDER_UNAVAILABLE", True),
    }.get(status_code, ("MODEL_PROVIDER_FAILED", status_code >= 500))


def _provider_error(
    code: str,
    *,
    retryable: bool,
    network_calls: int,
) -> ModelProviderError:
    return ModelProviderError(
        code,
        "The DeepSeek provider adapter did not return a trusted result.",
        retryable=retryable,
        next_action="Review sanitized provider evidence before a new authorized call.",
        physical_network_calls=network_calls,
    )


def _read_bounded(response: Any) -> bytes:
    raw = bytes(response.read(_MAX_RESPONSE_BYTES + 1))
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise _TransportFailure("MODEL_PROVIDER_RESPONSE_TOO_LARGE", retryable=False)
    return raw
