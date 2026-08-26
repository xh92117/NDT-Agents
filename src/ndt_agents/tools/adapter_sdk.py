"""Provider-neutral adapter SDK with exact transport and evidence bindings."""

from __future__ import annotations

import ipaddress
import json
import re
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal, Protocol, Self
from urllib.parse import urlsplit, urlunsplit

from jsonschema import Draft202012Validator
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import Field, field_validator, model_validator
from pydantic import ValidationError as PydanticValidationError

from ndt_agents.contracts.v1 import ArtifactRef, StrictModel, TenantScope, ToolResult, ToolStatus
from ndt_agents.tools.registry import (
    IdempotencyPolicy,
    NetworkPolicy,
    SideEffectClass,
    ToolDataDestination,
    ToolDataScope,
    ToolDefinition,
    ToolInvocation,
    ToolKind,
    ToolRecoveryPolicy,
    ToolTransport,
    canonical_sha256,
)
from ndt_agents.tools.schema_policy import plaintext_secret_fields

ADAPTER_SDK_CONTRACT_VERSION: Literal["1.0.0"] = "1.0.0"

_IDENTIFIER = r"^[a-z][a-z0-9_.-]{0,127}$"
_OPERATION = r"^[a-z][a-z0-9_-]{0,63}$"
_SEMVER = r"^[0-9]+\.[0-9]+\.[0-9]+$"
_ENTRY_POINT = r"^[A-Za-z_][A-Za-z0-9_.:]{0,255}$"
_MEDIA_TYPE = r"^[a-z0-9][a-z0-9.+-]{0,63}/[a-z0-9][a-z0-9.+-]{0,127}$"
_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
_ALLOWED_TRANSPORTS = frozenset(
    {
        ToolTransport.BASH,
        ToolTransport.HTTP_API,
        ToolTransport.SDK,
        ToolTransport.DLL,
        ToolTransport.FILE_EXCHANGE,
        ToolTransport.MCP,
        ToolTransport.SIMULATOR,
    }
)
_STANDARD_ADAPTER_ERRORS = frozenset(
    {
        "ADAPTER_ARTIFACT_INVALID",
        "ADAPTER_OUTPUT_INVALID",
        "ADAPTER_PROVIDER_FAILED",
        "ADAPTER_PROVIDER_UNAVAILABLE",
        "ADAPTER_PROVENANCE_INVALID",
        "ADAPTER_RESPONSE_INVALID",
    }
)
_REGISTRATION_SET_FIELDS = (
    "required_permissions",
    "secret_purposes",
    "declared_error_codes",
)


class AdapterCapabilityFamily(StrEnum):
    INSTRUMENT = "INSTRUMENT"
    ENGINEERING_APPLICATION = "ENGINEERING_APPLICATION"
    AI_MODEL = "AI_MODEL"


class AdapterOrigin(StrEnum):
    SIMULATED = "SIMULATED"
    LABORATORY = "LABORATORY"
    PRODUCTION = "PRODUCTION"


class AdapterProviderStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class AdapterTransportBinding(StrictModel):
    schema_version: Literal["1.0.0"] = ADAPTER_SDK_CONTRACT_VERSION
    transport: ToolTransport
    command_id: str | None = Field(default=None, pattern=_IDENTIFIER)
    executable_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    package_name: str | None = Field(default=None, pattern=_IDENTIFIER)
    package_version: str | None = Field(default=None, pattern=_SEMVER)
    package_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    library_id: str | None = Field(default=None, pattern=_IDENTIFIER)
    library_version: str | None = Field(default=None, pattern=_SEMVER)
    library_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    entry_point: str | None = Field(default=None, pattern=_ENTRY_POINT)
    exchange_root_id: str | None = Field(default=None, pattern=_IDENTIFIER)
    exchange_media_type: str | None = Field(default=None, pattern=_MEDIA_TYPE)
    mcp_server_registration_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    mcp_namespace: str | None = Field(default=None, pattern=_IDENTIFIER)
    simulator_id: str | None = Field(default=None, pattern=_IDENTIFIER)
    simulator_version: str | None = Field(default=None, pattern=_SEMVER)
    simulator_fixture_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("base_url", mode="before")
    @classmethod
    def canonicalize_base_url(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return _canonical_https_base_url(value)

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if self.transport not in _ALLOWED_TRANSPORTS:
            raise ValueError("adapter transport is not supported by the SDK")
        required: dict[ToolTransport, frozenset[str]] = {
            ToolTransport.BASH: frozenset({"command_id", "executable_sha256"}),
            ToolTransport.HTTP_API: frozenset({"base_url"}),
            ToolTransport.SDK: frozenset(
                {"package_name", "package_version", "package_sha256", "entry_point"}
            ),
            ToolTransport.DLL: frozenset(
                {"library_id", "library_version", "library_sha256", "entry_point"}
            ),
            ToolTransport.FILE_EXCHANGE: frozenset({"exchange_root_id", "exchange_media_type"}),
            ToolTransport.MCP: frozenset({"mcp_server_registration_sha256", "mcp_namespace"}),
            ToolTransport.SIMULATOR: frozenset(
                {"simulator_id", "simulator_version", "simulator_fixture_sha256"}
            ),
        }
        values = self.model_dump(exclude={"schema_version", "transport", "binding_sha256"})
        populated = frozenset(key for key, value in values.items() if value is not None)
        if populated != required[self.transport]:
            raise ValueError("adapter transport fields do not match the selected transport")
        if self.binding_sha256 != adapter_transport_binding_sha256(self):
            raise ValueError("adapter transport binding hash is invalid")
        return self


class AdapterRegistration(StrictModel):
    schema_version: Literal["1.0.0"] = ADAPTER_SDK_CONTRACT_VERSION
    adapter_id: str = Field(pattern=_IDENTIFIER)
    adapter_version: str = Field(pattern=_SEMVER)
    capability_family: AdapterCapabilityFamily
    origin: AdapterOrigin
    purpose: str = Field(min_length=1, max_length=1000)
    operation: str = Field(pattern=_OPERATION)
    binding: AdapterTransportBinding
    data_scope: ToolDataScope = ToolDataScope.TASK
    data_destination: ToolDataDestination
    side_effect: SideEffectClass
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    required_permissions: frozenset[str] = Field(min_length=1, max_length=32)
    secret_purposes: frozenset[str] = Field(default=frozenset(), max_length=16)
    network: NetworkPolicy
    approval_required: bool = False
    idempotency: IdempotencyPolicy
    timeout_ms: int = Field(ge=1, le=3_600_000)
    max_attempts: int = Field(ge=1, le=3)
    max_concurrency: int = Field(ge=1, le=16)
    max_input_bytes: int = Field(ge=1, le=10_000_000)
    max_output_bytes: int = Field(ge=1, le=99_750_000)
    max_tokens: int = Field(default=0, ge=0, le=1_000_000)
    recovery_policy: ToolRecoveryPolicy
    requires_device_identity: bool = False
    requires_calibration: bool = False
    requires_model_identity: bool = False
    declared_error_codes: frozenset[str] = Field(min_length=1, max_length=128)
    audit_owner: str = Field(pattern=_IDENTIFIER)
    test_owner: str = Field(pattern=_IDENTIFIER)
    registration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_registration(self) -> Self:
        _validate_strict_schema(self.input_schema)
        _validate_strict_schema(self.output_schema)
        if plaintext_secret_fields(self.input_schema):
            raise ValueError("adapter input schema cannot accept plaintext credential fields")
        if any(re.fullmatch(_IDENTIFIER, item) is None for item in self.required_permissions):
            raise ValueError("adapter permissions must use stable identifiers")
        if any(re.fullmatch(_IDENTIFIER, item) is None for item in self.secret_purposes):
            raise ValueError("adapter secret purposes must use stable identifiers")
        if any(_ERROR_CODE.fullmatch(item) is None for item in self.declared_error_codes):
            raise ValueError("adapter error codes must be stable uppercase identifiers")
        if self.side_effect is not SideEffectClass.READ_ONLY:
            if self.idempotency is not IdempotencyPolicy.REQUIRED or self.max_concurrency != 1:
                raise ValueError("side-effect adapters require idempotency and serial execution")
        if self.side_effect is SideEffectClass.IRREVERSIBLE and not self.approval_required:
            raise ValueError("irreversible adapters require approval")
        if self.max_attempts > 1:
            if (
                self.side_effect is not SideEffectClass.READ_ONLY
                or self.recovery_policy is not ToolRecoveryPolicy.RETRY_READ_ONLY
            ):
                raise ValueError("multiple attempts require read-only retry recovery")
        if self.recovery_policy is ToolRecoveryPolicy.RETRY_READ_ONLY and (
            self.side_effect is not SideEffectClass.READ_ONLY or self.max_attempts < 2
        ):
            raise ValueError("read-only retry recovery requires multiple read-only attempts")
        if self.side_effect is not SideEffectClass.READ_ONLY and self.recovery_policy not in {
            ToolRecoveryPolicy.RECONCILE,
            ToolRecoveryPolicy.HUMAN_REVIEW,
        }:
            raise ValueError("side-effect adapters require reconciliation or human review")
        if self.recovery_policy is ToolRecoveryPolicy.HUMAN_REVIEW and not self.approval_required:
            raise ValueError("human-review recovery requires approval")
        self._validate_transport_policy()
        if self.capability_family is AdapterCapabilityFamily.INSTRUMENT:
            if not self.requires_device_identity:
                raise ValueError("instrument adapters require device identity")
        if self.requires_calibration and not self.requires_device_identity:
            raise ValueError("calibration provenance requires device identity")
        if self.capability_family is AdapterCapabilityFamily.AI_MODEL:
            if (
                not self.requires_model_identity
                or self.max_tokens < 1
                or self.side_effect is not SideEffectClass.READ_ONLY
            ):
                raise ValueError(
                    "AI-model adapters require model identity and read-only token budget"
                )
            if self.binding.transport not in {
                ToolTransport.BASH,
                ToolTransport.HTTP_API,
                ToolTransport.SDK,
                ToolTransport.MCP,
                ToolTransport.SIMULATOR,
            }:
                raise ValueError("AI-model adapter transport is unsupported")
        elif self.max_tokens != 0:
            raise ValueError("only AI-model adapters may declare a token budget")
        if self.registration_sha256 != adapter_registration_sha256(self):
            raise ValueError("adapter registration hash is invalid")
        return self

    def _validate_transport_policy(self) -> None:
        transport = self.binding.transport
        local_only = {
            ToolTransport.BASH,
            ToolTransport.DLL,
            ToolTransport.FILE_EXCHANGE,
            ToolTransport.SIMULATOR,
        }
        if transport in local_only and (
            self.network is not NetworkPolicy.NONE
            or self.data_destination is not ToolDataDestination.LOCAL
        ):
            raise ValueError("local adapter transport requires local network-free execution")
        if transport is ToolTransport.HTTP_API and (
            self.network is not NetworkPolicy.RESTRICTED
            or self.data_destination is not ToolDataDestination.APPROVED_EXTERNAL
        ):
            raise ValueError("HTTP adapters require restricted approved-external execution")
        if self.data_destination is ToolDataDestination.APPROVED_EXTERNAL and (
            self.network is not NetworkPolicy.RESTRICTED
        ):
            raise ValueError("external adapter destinations require restricted network")
        if transport is ToolTransport.SIMULATOR and (
            self.origin is not AdapterOrigin.SIMULATED
            or self.secret_purposes
            or self.side_effect is not SideEffectClass.READ_ONLY
        ):
            raise ValueError("simulators must be local credential-free read-only simulations")
        if self.origin is AdapterOrigin.SIMULATED and transport is not ToolTransport.SIMULATOR:
            raise ValueError("simulated origin requires the simulator transport")


class AdapterExecutionRequest(StrictModel):
    schema_version: Literal["1.0.0"] = ADAPTER_SDK_CONTRACT_VERSION
    call_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    task_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    run_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    scope: TenantScope
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    adapter_id: str = Field(pattern=_IDENTIFIER)
    adapter_version: str = Field(pattern=_SEMVER)
    registration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    operation: str = Field(pattern=_OPERATION)
    transport: ToolTransport
    transport_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    arguments: dict[str, Any]
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str | None = Field(default=None, max_length=256)
    deadline_at: datetime
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        _require_utc(self.deadline_at, "adapter deadline")
        if self.input_sha256 != canonical_sha256(self.arguments):
            raise ValueError("adapter request input hash is invalid")
        if self.request_sha256 != adapter_execution_request_sha256(self):
            raise ValueError("adapter execution request hash is invalid")
        return self


class AdapterProviderReply(StrictModel):
    schema_version: Literal["1.0.0"] = ADAPTER_SDK_CONTRACT_VERSION
    adapter_id: str = Field(pattern=_IDENTIFIER)
    adapter_version: str = Field(pattern=_SEMVER)
    registration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: AdapterProviderStatus
    output: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")
    retryable: bool = False
    artifacts: tuple[ArtifactRef, ...] = Field(default=(), max_length=64)
    provider_operation_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
    device_identity: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$"
    )
    calibration_ids: tuple[str, ...] = Field(default=(), max_length=64)
    model_identity: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$"
    )
    bytes_read: int = Field(default=0, ge=0, le=1_000_000_000)
    bytes_written: int = Field(default=0, ge=0, le=1_000_000_000)

    @model_validator(mode="after")
    def validate_reply(self) -> Self:
        if (self.status is AdapterProviderStatus.SUCCESS) != (self.error_code is None):
            raise ValueError("adapter provider status and error are inconsistent")
        if self.status is AdapterProviderStatus.SUCCESS and self.retryable:
            raise ValueError("successful adapter provider replies cannot be retryable")
        if (
            self.status
            not in {
                AdapterProviderStatus.SUCCESS,
                AdapterProviderStatus.PARTIAL_SUCCESS,
            }
            and self.output
        ):
            raise ValueError("failed adapter provider replies cannot contain output")
        if self.calibration_ids != tuple(sorted(set(self.calibration_ids))):
            raise ValueError("adapter calibration identities must be sorted and unique")
        return self


class AdapterEvidence(StrictModel):
    schema_version: Literal["1.0.0"] = ADAPTER_SDK_CONTRACT_VERSION
    scope: TenantScope
    task_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    run_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    call_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    adapter_id: str = Field(pattern=_IDENTIFIER)
    adapter_version: str = Field(pattern=_SEMVER)
    registration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transport: ToolTransport
    transport_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    origin: AdapterOrigin
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")
    artifact_bindings: tuple[str, ...] = Field(max_length=64)
    provider_operation_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$"
    )
    device_identity: str | None = Field(default=None, max_length=256)
    calibration_ids: tuple[str, ...] = Field(default=(), max_length=64)
    model_identity: str | None = Field(default=None, max_length=256)
    bytes_read: int = Field(ge=0)
    bytes_written: int = Field(ge=0)
    provider_calls: Literal[1] = 1
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=0)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        _require_utc(self.started_at, "adapter start time")
        _require_utc(self.completed_at, "adapter completion time")
        if self.completed_at < self.started_at:
            raise ValueError("adapter completion precedes start")
        if self.evidence_sha256 != adapter_evidence_sha256(self):
            raise ValueError("adapter evidence hash is invalid")
        return self


class AdapterOutputEnvelope(StrictModel):
    schema_version: Literal["1.0.0"] = ADAPTER_SDK_CONTRACT_VERSION
    status: AdapterProviderStatus
    trust: Literal["UNTRUSTED"] = "UNTRUSTED"
    review_required: Literal[True] = True
    output: dict[str, Any]
    evidence: AdapterEvidence
    envelope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        if self.envelope_sha256 != adapter_output_envelope_sha256(self):
            raise ValueError("adapter output envelope hash is invalid")
        return self


class AdapterProviderError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__("The registered adapter provider did not complete the request.")


class _AdapterValidationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("The adapter provider reply failed contract validation.")


class AdapterProvider(Protocol):
    async def execute(
        self, request: AdapterExecutionRequest
    ) -> AdapterProviderReply | Mapping[str, Any]: ...


class RegisteredAdapter:
    """Shared ToolAdapter wrapper around one exact injected provider."""

    def __init__(
        self,
        registration: AdapterRegistration,
        provider: AdapterProvider,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.registration = registration
        self._provider = provider
        self._clock = clock

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        monotonic_started = time.monotonic()
        started_at = self._clock()
        request = _execution_request(self.registration, invocation, started_at)
        try:
            raw_reply = await self._provider.execute(request)
            reply = AdapterProviderReply.model_validate(raw_reply, strict=True)
            self._validate_reply(invocation, request, reply)
            return self._from_reply(
                invocation,
                request,
                reply,
                started_at=started_at,
                monotonic_started=monotonic_started,
            )
        except AdapterProviderError as error:
            code = (
                error.code
                if error.code in self.registration.declared_error_codes
                or error.code in _STANDARD_ADAPTER_ERRORS
                else "ADAPTER_RESPONSE_INVALID"
            )
            retryable = (
                error.retryable and self._retry_allowed() and code != "ADAPTER_RESPONSE_INVALID"
            )
            return self._failure(
                invocation,
                request,
                code=code,
                status=(
                    ToolStatus.BLOCKED
                    if code == "ADAPTER_PROVIDER_UNAVAILABLE"
                    else ToolStatus.FAILED
                ),
                retryable=retryable,
                started_at=started_at,
                monotonic_started=monotonic_started,
            )
        except _AdapterValidationError as error:
            return self._failure(
                invocation,
                request,
                code=error.code,
                status=ToolStatus.FAILED,
                retryable=False,
                started_at=started_at,
                monotonic_started=monotonic_started,
            )
        except (PydanticValidationError, JsonSchemaValidationError, TypeError, ValueError):
            return self._failure(
                invocation,
                request,
                code="ADAPTER_RESPONSE_INVALID",
                status=ToolStatus.FAILED,
                retryable=False,
                started_at=started_at,
                monotonic_started=monotonic_started,
            )
        except Exception:
            return self._failure(
                invocation,
                request,
                code="ADAPTER_PROVIDER_FAILED",
                status=ToolStatus.FAILED,
                retryable=self._retry_allowed(),
                started_at=started_at,
                monotonic_started=monotonic_started,
            )

    def _validate_reply(
        self,
        invocation: ToolInvocation,
        request: AdapterExecutionRequest,
        reply: AdapterProviderReply,
    ) -> None:
        registration = self.registration
        if (
            reply.adapter_id != registration.adapter_id
            or reply.adapter_version != registration.adapter_version
            or reply.registration_sha256 != registration.registration_sha256
            or reply.request_sha256 != request.request_sha256
        ):
            raise _AdapterValidationError("ADAPTER_RESPONSE_INVALID")
        if reply.error_code is not None and reply.error_code not in (
            registration.declared_error_codes | _STANDARD_ADAPTER_ERRORS
        ):
            raise _AdapterValidationError("ADAPTER_RESPONSE_INVALID")
        if reply.retryable and not self._retry_allowed():
            raise _AdapterValidationError("ADAPTER_RESPONSE_INVALID")
        if reply.status in {
            AdapterProviderStatus.SUCCESS,
            AdapterProviderStatus.PARTIAL_SUCCESS,
        }:
            try:
                Draft202012Validator(registration.output_schema).validate(reply.output)
            except JsonSchemaValidationError as error:
                raise _AdapterValidationError("ADAPTER_OUTPUT_INVALID") from error
            output_bytes = len(
                json.dumps(reply.output, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
            if output_bytes > registration.max_output_bytes:
                raise _AdapterValidationError("ADAPTER_OUTPUT_INVALID")
            if registration.requires_device_identity and reply.device_identity is None:
                raise _AdapterValidationError("ADAPTER_PROVENANCE_INVALID")
            if registration.requires_calibration and not reply.calibration_ids:
                raise _AdapterValidationError("ADAPTER_PROVENANCE_INVALID")
            if registration.requires_model_identity and reply.model_identity is None:
                raise _AdapterValidationError("ADAPTER_PROVENANCE_INVALID")
        _validate_artifacts(invocation.context.scope, reply.artifacts)

    def _from_reply(
        self,
        invocation: ToolInvocation,
        request: AdapterExecutionRequest,
        reply: AdapterProviderReply,
        *,
        started_at: datetime,
        monotonic_started: float,
    ) -> ToolResult:
        status_map = {
            AdapterProviderStatus.SUCCESS: ToolStatus.SUCCESS,
            AdapterProviderStatus.PARTIAL_SUCCESS: ToolStatus.PARTIAL_SUCCESS,
            AdapterProviderStatus.FAILED: ToolStatus.FAILED,
            AdapterProviderStatus.BLOCKED: ToolStatus.BLOCKED,
            AdapterProviderStatus.CANCELLED: ToolStatus.CANCELLED,
        }
        return self._result(
            invocation,
            request,
            provider_status=reply.status,
            output=reply.output,
            artifacts=reply.artifacts,
            provider_operation_id=reply.provider_operation_id,
            device_identity=reply.device_identity,
            calibration_ids=reply.calibration_ids,
            model_identity=reply.model_identity,
            bytes_read=reply.bytes_read,
            bytes_written=reply.bytes_written,
            status=status_map[reply.status],
            error_code=reply.error_code,
            retryable=reply.retryable,
            started_at=started_at,
            monotonic_started=monotonic_started,
        )

    def _failure(
        self,
        invocation: ToolInvocation,
        request: AdapterExecutionRequest,
        *,
        code: str,
        status: ToolStatus,
        retryable: bool,
        started_at: datetime,
        monotonic_started: float,
    ) -> ToolResult:
        return self._result(
            invocation,
            request,
            provider_status=(
                AdapterProviderStatus.BLOCKED
                if status is ToolStatus.BLOCKED
                else AdapterProviderStatus.FAILED
            ),
            output={},
            artifacts=(),
            provider_operation_id=None,
            device_identity=None,
            calibration_ids=(),
            model_identity=None,
            bytes_read=0,
            bytes_written=0,
            status=status,
            error_code=code,
            retryable=retryable,
            started_at=started_at,
            monotonic_started=monotonic_started,
        )

    def _result(
        self,
        invocation: ToolInvocation,
        request: AdapterExecutionRequest,
        *,
        provider_status: AdapterProviderStatus,
        output: dict[str, Any],
        artifacts: tuple[ArtifactRef, ...],
        provider_operation_id: str | None,
        device_identity: str | None,
        calibration_ids: tuple[str, ...],
        model_identity: str | None,
        bytes_read: int,
        bytes_written: int,
        status: ToolStatus,
        error_code: str | None,
        retryable: bool,
        started_at: datetime,
        monotonic_started: float,
    ) -> ToolResult:
        completed_at = self._clock()
        duration_ms = max(0, int((time.monotonic() - monotonic_started) * 1000))
        evidence = _evidence(
            invocation,
            request,
            self.registration,
            output,
            artifacts,
            provider_operation_id,
            device_identity,
            calibration_ids,
            model_identity,
            bytes_read,
            bytes_written,
            error_code,
            started_at,
            completed_at,
            duration_ms,
        )
        envelope = _envelope(provider_status, output, evidence)
        payload = envelope.model_dump(mode="json")
        return ToolResult(
            call_id=invocation.call_id,
            task_id=invocation.context.task_id,
            run_id=invocation.context.run_id,
            scope=invocation.context.scope,
            tool_name=invocation.definition.name,
            tool_version=invocation.definition.version,
            status=status,
            output=payload,
            exit_code=0 if status is ToolStatus.SUCCESS else None,
            stdout="",
            stderr="",
            encoding="utf-8",
            truncated=False,
            artifacts=artifacts,
            idempotency_key=invocation.idempotency_key,
            input_sha256=invocation.input_sha256,
            output_sha256=canonical_sha256(payload),
            error_code=error_code,
            retryable=retryable,
            duration_ms=duration_ms,
            completed_at=completed_at,
        )

    def _retry_allowed(self) -> bool:
        return bool(
            self.registration.side_effect is SideEffectClass.READ_ONLY
            and self.registration.recovery_policy is ToolRecoveryPolicy.RETRY_READ_ONLY
        )


def adapter_tool_definition(registration: AdapterRegistration) -> ToolDefinition:
    kind = (
        ToolKind.AI_MODEL
        if registration.capability_family is AdapterCapabilityFamily.AI_MODEL
        else ToolKind.INSTRUMENT
    )
    namespace = (
        registration.binding.mcp_namespace
        if registration.binding.transport is ToolTransport.MCP
        else None
    )
    test_groups = {"INT-INSTRUMENT", "SEC-TOOLS"}
    if registration.binding.transport is ToolTransport.BASH:
        test_groups.add("SEC-BASH")
    if kind is ToolKind.AI_MODEL:
        test_groups.add("UNIT-MODELREG")
    return ToolDefinition(
        name=f"adapter.{registration.adapter_id}.{registration.operation}",
        version=registration.adapter_version,
        purpose=registration.purpose,
        kind=kind,
        transport=registration.binding.transport,
        namespace=namespace,
        data_scope=registration.data_scope,
        data_destination=registration.data_destination,
        side_effect=registration.side_effect,
        input_schema=registration.input_schema,
        output_schema=_adapter_envelope_schema(registration.registration_sha256),
        required_permissions=registration.required_permissions,
        timeout_ms=registration.timeout_ms,
        max_attempts=registration.max_attempts,
        max_concurrency=registration.max_concurrency,
        max_input_bytes=registration.max_input_bytes,
        max_output_bytes=min(100_000_000, registration.max_output_bytes + 250_000),
        max_tokens=registration.max_tokens,
        idempotency=registration.idempotency,
        secret_purposes=registration.secret_purposes,
        network=registration.network,
        approval_required=registration.approval_required,
        declared_error_codes=registration.declared_error_codes | _STANDARD_ADAPTER_ERRORS,
        recovery_policy=registration.recovery_policy,
        audit_owner=registration.audit_owner,
        test_owner=registration.test_owner,
        test_groups=frozenset(test_groups),
    )


def adapter_transport_binding_sha256(binding: AdapterTransportBinding) -> str:
    return canonical_sha256(binding.model_dump(mode="json", exclude={"binding_sha256"}))


def adapter_registration_sha256(registration: AdapterRegistration) -> str:
    payload = registration.model_dump(mode="json", exclude={"registration_sha256"})
    return canonical_sha256(_canonicalize_adapter_registration_sets(payload))


def _canonicalize_adapter_registration_sets(payload: Mapping[str, Any]) -> dict[str, Any]:
    canonical = dict(payload)
    for field_name in _REGISTRATION_SET_FIELDS:
        canonical[field_name] = sorted(canonical[field_name])
    return canonical


def adapter_execution_request_sha256(request: AdapterExecutionRequest) -> str:
    return canonical_sha256(request.model_dump(mode="json", exclude={"request_sha256"}))


def adapter_evidence_sha256(evidence: AdapterEvidence) -> str:
    return canonical_sha256(evidence.model_dump(mode="json", exclude={"evidence_sha256"}))


def adapter_output_envelope_sha256(envelope: AdapterOutputEnvelope) -> str:
    return canonical_sha256(envelope.model_dump(mode="json", exclude={"envelope_sha256"}))


def _execution_request(
    registration: AdapterRegistration,
    invocation: ToolInvocation,
    started_at: datetime,
) -> AdapterExecutionRequest:
    draft = AdapterExecutionRequest.model_construct(
        call_id=str(invocation.call_id),
        task_id=str(invocation.context.task_id),
        run_id=str(invocation.context.run_id),
        scope=invocation.context.scope,
        request_id=invocation.context.request_id,
        adapter_id=registration.adapter_id,
        adapter_version=registration.adapter_version,
        registration_sha256=registration.registration_sha256,
        operation=registration.operation,
        transport=registration.binding.transport,
        transport_binding_sha256=registration.binding.binding_sha256,
        arguments=invocation.arguments,
        input_sha256=invocation.input_sha256,
        idempotency_key=invocation.idempotency_key,
        deadline_at=started_at + timedelta(milliseconds=registration.timeout_ms),
        request_sha256="0" * 64,
    )
    payload = draft.model_dump(mode="json", exclude={"request_sha256"})
    return AdapterExecutionRequest.model_validate(
        {**payload, "request_sha256": canonical_sha256(payload)}
    )


def _evidence(
    invocation: ToolInvocation,
    request: AdapterExecutionRequest,
    registration: AdapterRegistration,
    output: dict[str, Any],
    artifacts: tuple[ArtifactRef, ...],
    provider_operation_id: str | None,
    device_identity: str | None,
    calibration_ids: tuple[str, ...],
    model_identity: str | None,
    bytes_read: int,
    bytes_written: int,
    error_code: str | None,
    started_at: datetime,
    completed_at: datetime,
    duration_ms: int,
) -> AdapterEvidence:
    draft = AdapterEvidence.model_construct(
        scope=invocation.context.scope,
        task_id=str(invocation.context.task_id),
        run_id=str(invocation.context.run_id),
        call_id=str(invocation.call_id),
        adapter_id=registration.adapter_id,
        adapter_version=registration.adapter_version,
        registration_sha256=registration.registration_sha256,
        transport=registration.binding.transport,
        transport_binding_sha256=registration.binding.binding_sha256,
        origin=registration.origin,
        input_sha256=request.input_sha256,
        output_sha256=canonical_sha256(output),
        error_code=error_code,
        artifact_bindings=tuple(
            sorted(
                f"{item.artifact_id}:{canonical_sha256(item.model_dump(mode='json'))}"
                for item in artifacts
            )
        ),
        provider_operation_id=provider_operation_id,
        device_identity=device_identity,
        calibration_ids=calibration_ids,
        model_identity=model_identity,
        bytes_read=bytes_read,
        bytes_written=bytes_written,
        provider_calls=1,
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=duration_ms,
        evidence_sha256="0" * 64,
    )
    payload = draft.model_dump(mode="json", exclude={"evidence_sha256"})
    return AdapterEvidence.model_validate({**payload, "evidence_sha256": canonical_sha256(payload)})


def _envelope(
    status: AdapterProviderStatus,
    output: dict[str, Any],
    evidence: AdapterEvidence,
) -> AdapterOutputEnvelope:
    draft = AdapterOutputEnvelope.model_construct(
        status=status,
        output=output,
        evidence=evidence,
        envelope_sha256="0" * 64,
    )
    payload = draft.model_dump(mode="json", exclude={"envelope_sha256"})
    return AdapterOutputEnvelope.model_validate(
        {**payload, "envelope_sha256": canonical_sha256(payload)}
    )


def _validate_artifacts(scope: TenantScope, artifacts: tuple[ArtifactRef, ...]) -> None:
    if any(item.scope != scope or not item.immutable for item in artifacts):
        raise _AdapterValidationError("ADAPTER_ARTIFACT_INVALID")
    if len({item.artifact_id for item in artifacts}) != len(artifacts):
        raise _AdapterValidationError("ADAPTER_ARTIFACT_INVALID")


def _validate_strict_schema(schema: Mapping[str, Any]) -> None:
    Draft202012Validator.check_schema(schema)
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise ValueError("adapter schemas must be strict objects")


def _canonical_https_base_url(value: str) -> str:
    if value != value.strip() or any(ord(char) < 32 or char.isspace() for char in value):
        raise ValueError("adapter HTTP endpoint contains unsafe characters")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
    ):
        raise ValueError("adapter HTTP endpoint is unsafe")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"}:
        raise ValueError("adapter HTTP endpoint cannot use localhost")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("adapter HTTP endpoint cannot use a literal IP")
    labels = host.split(".")
    if any(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None for label in labels
    ):
        raise ValueError("adapter HTTP endpoint host is invalid")
    if parsed.port not in {None, 443}:
        raise ValueError("adapter HTTP endpoint uses an unapproved port")
    return urlunsplit(("https", host, parsed.path or "", "", ""))


def _require_utc(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{label} must use UTC")


def _adapter_envelope_schema(registration_sha256: str) -> dict[str, Any]:
    return {
        "$comment": f"Adapter registration SHA-256: {registration_sha256}",
        "type": "object",
        "properties": {
            "schema_version": {"const": ADAPTER_SDK_CONTRACT_VERSION},
            "status": {"enum": [item.value for item in AdapterProviderStatus]},
            "trust": {"const": "UNTRUSTED"},
            "review_required": {"const": True},
            "output": {"type": "object"},
            "evidence": {"type": "object"},
            "envelope_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        },
        "required": [
            "schema_version",
            "status",
            "trust",
            "review_required",
            "output",
            "evidence",
            "envelope_sha256",
        ],
        "additionalProperties": False,
    }
