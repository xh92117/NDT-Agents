"""Provider-neutral Function Calling catalog and strict invocation gateway."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal, NoReturn, Self
from uuid import uuid4

from jsonschema import Draft202012Validator
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import Field, model_validator
from pydantic import ValidationError as PydanticValidationError

from ndt_agents.contracts.v1 import StrictModel, ToolResult, ToolStatus
from ndt_agents.observability.audit import AuditKind, AuditOutcome, AuditRecord, AuditService
from ndt_agents.observability.tracing import TraceService
from ndt_agents.orchestration.budget import BudgetGuard
from ndt_agents.tools.registry import (
    HARD_EXPOSED_TOOLS,
    ExposedTool,
    SideEffectClass,
    ToolExposurePolicy,
    ToolInvocationContext,
    ToolKind,
    ToolRegistry,
    canonical_sha256,
)

FUNCTION_GATEWAY_CONTRACT_VERSION: Literal["1.0.0"] = "1.0.0"
DEFAULT_FUNCTION_CALL_BYTES = 65_536
HARD_FUNCTION_CALL_BYTES = 1_000_000

_FUNCTION_NAME_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class FunctionSchema(StrictModel):
    """The only function-definition fields allowed into model context."""

    name: str = Field(pattern=_FUNCTION_NAME_PATTERN)
    description: str = Field(min_length=1, max_length=1000)
    parameters: dict[str, Any]
    strict: Literal[True] = True

    @model_validator(mode="after")
    def validate_parameters(self) -> Self:
        if _invalid_schema_references(self.parameters):
            raise ValueError(
                "function schemas permit only resolvable local JSON Pointer references"
            )
        Draft202012Validator.check_schema(self.parameters)
        if (
            self.parameters.get("type") != "object"
            or self.parameters.get("additionalProperties") is not False
        ):
            raise ValueError("function parameters must be a strict object schema")
        return self


class FunctionBinding(StrictModel):
    """Internal exact mapping from a model-visible function to one registry entry."""

    schema_version: Literal["1.0.0"] = FUNCTION_GATEWAY_CONTRACT_VERSION
    function: FunctionSchema
    tool_name: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    tool_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    tool_kind: ToolKind
    side_effect: SideEffectClass
    approval_required: bool
    schema_sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_schema_hash(self) -> Self:
        if self.schema_sha256 != canonical_sha256(self._hash_payload()):
            raise ValueError("function binding schema hash is invalid")
        return self

    def _hash_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "function": self.function.model_dump(mode="json"),
            "tool_name": self.tool_name,
            "tool_version": self.tool_version,
            "tool_kind": self.tool_kind,
            "side_effect": self.side_effect,
            "approval_required": self.approval_required,
        }


class FunctionCatalog(StrictModel):
    """Hash-bound catalog retained by orchestration, not serialized into model context."""

    schema_version: Literal["1.0.0"] = FUNCTION_GATEWAY_CONTRACT_VERSION
    registry_version: str = Field(pattern=_SHA256_PATTERN)
    exposure_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    authorization_context_sha256: str = Field(pattern=_SHA256_PATTERN)
    bindings: tuple[FunctionBinding, ...] = Field(min_length=1, max_length=HARD_EXPOSED_TOOLS)
    catalog_sha256: str = Field(pattern=_SHA256_PATTERN)
    gateway_attestation_sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_catalog(self) -> Self:
        names = [binding.function.name for binding in self.bindings]
        tool_keys = [f"{binding.tool_name}@{binding.tool_version}" for binding in self.bindings]
        if len(set(names)) != len(names) or len(set(tool_keys)) != len(tool_keys):
            raise ValueError("function catalog bindings must be unique")
        if tool_keys != sorted(tool_keys):
            raise ValueError("function catalog bindings must use deterministic tool ordering")
        if self.catalog_sha256 != canonical_sha256(self._hash_payload()):
            raise ValueError("function catalog hash is invalid")
        return self

    def model_schemas(self) -> tuple[FunctionSchema, ...]:
        """Return the complete and minimal model-visible function surface."""

        return tuple(binding.function for binding in self.bindings)

    def _hash_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "registry_version": self.registry_version,
            "exposure_manifest_sha256": self.exposure_manifest_sha256,
            "authorization_context_sha256": self.authorization_context_sha256,
            "bindings": [binding.model_dump(mode="json") for binding in self.bindings],
        }


class FunctionCall(StrictModel):
    """Strict untrusted function-call envelope produced by a model provider."""

    call_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    name: str = Field(pattern=_FUNCTION_NAME_PATTERN)
    arguments: dict[str, Any]


class FunctionGatewayPolicy(StrictModel):
    schema_version: Literal["1.0.0"] = FUNCTION_GATEWAY_CONTRACT_VERSION
    max_call_bytes: int = Field(
        default=DEFAULT_FUNCTION_CALL_BYTES,
        ge=1,
        le=HARD_FUNCTION_CALL_BYTES,
    )


class FunctionGatewayError(RuntimeError):
    """Stable pre-registry Function Calling failure."""

    def __init__(self, code: str, message: str, *, retryable: bool, next_action: str) -> None:
        self.code = code
        self.retryable = retryable
        self.next_action = next_action
        super().__init__(message)


class _DuplicateJsonKey(ValueError):
    pass


class _NonFiniteJsonNumber(ValueError):
    pass


class FunctionGateway:
    """Load authorized schemas and execute validated calls through the shared registry."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        audit: AuditService,
        traces: TraceService,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        attestation_key: bytes | None = None,
    ) -> None:
        selected_key = secrets.token_bytes(32) if attestation_key is None else attestation_key
        if len(selected_key) < 32:
            raise ValueError("function catalog attestation keys must contain at least 32 bytes")
        self._registry = registry
        self._audit = audit
        self._traces = traces
        self._clock = clock
        self._attestation_key = bytes(selected_key)

    def load_catalog(
        self,
        context: ToolInvocationContext,
        *,
        exposure_policy: ToolExposurePolicy | None = None,
    ) -> FunctionCatalog:
        """Load one authorized registry exposure and attest its internal function bindings."""

        with self._traces.start_span("function.catalog"):
            manifest = self._registry.expose(context, policy=exposure_policy)
            try:
                bindings = tuple(
                    self._binding(tool)
                    for tool in sorted(
                        manifest.tools,
                        key=lambda item: f"{item.name}@{item.version}",
                    )
                )
                names = [binding.function.name for binding in bindings]
                if len(names) != len(set(names)):
                    self._deny(
                        "FUNCTION_NAME_COLLISION",
                        "Two exposed tools resolve to the same function name.",
                    )
                payload = {
                    "schema_version": FUNCTION_GATEWAY_CONTRACT_VERSION,
                    "registry_version": manifest.registry_version,
                    "exposure_manifest_sha256": manifest.manifest_sha256,
                    "authorization_context_sha256": self._context_sha256(context),
                    "bindings": [binding.model_dump(mode="json") for binding in bindings],
                }
                catalog_sha256 = canonical_sha256(payload)
                return FunctionCatalog(
                    registry_version=manifest.registry_version,
                    exposure_manifest_sha256=manifest.manifest_sha256,
                    authorization_context_sha256=self._context_sha256(context),
                    bindings=bindings,
                    catalog_sha256=catalog_sha256,
                    gateway_attestation_sha256=self._attest(catalog_sha256),
                )
            except FunctionGatewayError as error:
                self._record(
                    context,
                    target_id=manifest.registry_version,
                    action="function.deny",
                    decision=error.code,
                    outcome=AuditOutcome.DENIED,
                    input_sha256=manifest.manifest_sha256,
                    output_sha256=canonical_sha256({"error_code": error.code}),
                )
                raise
            except PydanticValidationError as error:
                mapped = FunctionGatewayError(
                    "FUNCTION_SCHEMA_INVALID",
                    "An exposed function schema cannot be loaded safely.",
                    retryable=False,
                    next_action="Correct and republish the registered tool schema.",
                )
                self._record(
                    context,
                    target_id=manifest.registry_version,
                    action="function.deny",
                    decision=mapped.code,
                    outcome=AuditOutcome.DENIED,
                    input_sha256=manifest.manifest_sha256,
                    output_sha256=canonical_sha256({"error_code": mapped.code}),
                )
                raise mapped from error

    async def invoke(
        self,
        raw_call: str | bytes,
        *,
        catalog: FunctionCatalog,
        context: ToolInvocationContext,
        budget: BudgetGuard,
        observation_sha256: str,
        policy: FunctionGatewayPolicy | None = None,
        idempotency_key: str | None = None,
        retry: bool = False,
        attempt_number: int = 1,
    ) -> ToolResult:
        """Validate one untrusted call, invoke the exact tool, and return its ToolResult."""

        raw_sha256 = self._raw_sha256(raw_call)
        call: FunctionCall | None = None
        with self._traces.start_span("function.invoke"):
            try:
                call = self._parse_call(raw_call, policy or FunctionGatewayPolicy())
                self._validate_catalog(catalog, context)
                binding = next(
                    (item for item in catalog.bindings if item.function.name == call.name),
                    None,
                )
                if binding is None:
                    self._deny(
                        "FUNCTION_UNAVAILABLE",
                        "The requested function is not present in the authorized catalog.",
                    )
                try:
                    Draft202012Validator(binding.function.parameters).validate(call.arguments)
                except JsonSchemaValidationError as error:
                    raise FunctionGatewayError(
                        "FUNCTION_ARGUMENTS_INVALID",
                        "The function arguments do not satisfy the published schema.",
                        retryable=False,
                        next_action="Correct the arguments using the current function schema.",
                    ) from error
                result = await self._registry.invoke(
                    name=binding.tool_name,
                    version=binding.tool_version,
                    arguments=call.arguments,
                    context=context,
                    budget=budget,
                    observation_sha256=observation_sha256,
                    idempotency_key=idempotency_key,
                    retry=retry,
                    attempt_number=attempt_number,
                )
                self._record(
                    context,
                    target_id=f"{call.name}:{call.call_id}",
                    action="function.execute",
                    decision=result.error_code or result.status.value,
                    outcome=(
                        AuditOutcome.SUCCESS
                        if result.status is ToolStatus.SUCCESS
                        else AuditOutcome.FAILED
                    ),
                    input_sha256=raw_sha256,
                    output_sha256=result.output_sha256 or canonical_sha256({}),
                )
                return result
            except FunctionGatewayError as error:
                self._record(
                    context,
                    target_id=(
                        f"{call.name}:{call.call_id}"
                        if call is not None
                        else self._registry.version
                    ),
                    action="function.deny",
                    decision=error.code,
                    outcome=AuditOutcome.DENIED,
                    input_sha256=raw_sha256,
                    output_sha256=canonical_sha256({"error_code": error.code}),
                )
                raise

    @staticmethod
    def _binding(tool: ExposedTool) -> FunctionBinding:
        function = FunctionSchema(
            name=_function_name(tool.name, tool.version),
            description=tool.purpose,
            parameters=tool.input_schema,
        )
        payload = {
            "schema_version": FUNCTION_GATEWAY_CONTRACT_VERSION,
            "function": function.model_dump(mode="json"),
            "tool_name": tool.name,
            "tool_version": tool.version,
            "tool_kind": tool.kind,
            "side_effect": tool.side_effect,
            "approval_required": tool.approval_required,
        }
        return FunctionBinding(
            function=function,
            tool_name=tool.name,
            tool_version=tool.version,
            tool_kind=tool.kind,
            side_effect=tool.side_effect,
            approval_required=tool.approval_required,
            schema_sha256=canonical_sha256(payload),
        )

    def _validate_catalog(
        self,
        catalog: FunctionCatalog,
        context: ToolInvocationContext,
    ) -> None:
        try:
            validated = FunctionCatalog.model_validate(catalog.model_dump(), strict=True)
        except PydanticValidationError as error:
            raise FunctionGatewayError(
                "FUNCTION_CATALOG_INVALID",
                "The function catalog failed structural or hash validation.",
                retryable=False,
                next_action="Reload the catalog through the current gateway.",
            ) from error
        if not hmac.compare_digest(
            validated.gateway_attestation_sha256,
            self._attest(validated.catalog_sha256),
        ):
            self._deny(
                "FUNCTION_CATALOG_UNTRUSTED",
                "The function catalog was not issued by this gateway instance.",
            )
        if (
            validated.registry_version != self._registry.version
            or context.expected_registry_version != self._registry.version
        ):
            self._deny(
                "FUNCTION_CATALOG_STALE",
                "The function catalog does not match the current registry snapshot.",
            )
        if validated.authorization_context_sha256 != self._context_sha256(context):
            self._deny(
                "FUNCTION_CONTEXT_MISMATCH",
                "The function catalog is bound to a different authorization context.",
            )

    @staticmethod
    def _parse_call(raw_call: str | bytes, policy: FunctionGatewayPolicy) -> FunctionCall:
        if isinstance(raw_call, str):
            try:
                encoded = raw_call.encode("utf-8")
            except UnicodeEncodeError as error:
                raise FunctionGatewayError(
                    "FUNCTION_ENCODING_INVALID",
                    "The function call is not valid UTF-8 text.",
                    retryable=False,
                    next_action="Return one UTF-8 JSON function-call object.",
                ) from error
        elif isinstance(raw_call, bytes):
            encoded = raw_call
        else:
            raise FunctionGatewayError(
                "FUNCTION_PAYLOAD_TYPE_INVALID",
                "The function call must be UTF-8 text or bytes.",
                retryable=False,
                next_action="Return one UTF-8 JSON function-call object.",
            )
        if len(encoded) > policy.max_call_bytes:
            raise FunctionGatewayError(
                "FUNCTION_PAYLOAD_TOO_LARGE",
                "The function call exceeds the active byte limit.",
                retryable=False,
                next_action="Reduce the function arguments before retrying.",
            )
        try:
            text = encoded.decode("utf-8")
            payload = json.loads(
                text,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_non_finite,
            )
        except UnicodeDecodeError as error:
            raise FunctionGatewayError(
                "FUNCTION_ENCODING_INVALID",
                "The function call is not valid UTF-8 text.",
                retryable=False,
                next_action="Return one UTF-8 JSON function-call object.",
            ) from error
        except _DuplicateJsonKey as error:
            raise FunctionGatewayError(
                "FUNCTION_JSON_DUPLICATE_KEY",
                "The function call contains a duplicate JSON key.",
                retryable=False,
                next_action="Return one unambiguous JSON object.",
            ) from error
        except _NonFiniteJsonNumber as error:
            raise FunctionGatewayError(
                "FUNCTION_JSON_NON_FINITE",
                "The function call contains a non-finite JSON number.",
                retryable=False,
                next_action="Use a finite JSON number or a schema-approved string.",
            ) from error
        except json.JSONDecodeError as error:
            raise FunctionGatewayError(
                "FUNCTION_JSON_INVALID",
                "The function call is not valid JSON.",
                retryable=False,
                next_action="Return one valid JSON object matching the call envelope.",
            ) from error
        except (RecursionError, ValueError) as error:
            raise FunctionGatewayError(
                "FUNCTION_JSON_INVALID",
                "The function call exceeds safe JSON parser constraints.",
                retryable=False,
                next_action="Return one bounded valid JSON object matching the call envelope.",
            ) from error
        try:
            return FunctionCall.model_validate(payload, strict=True)
        except PydanticValidationError as error:
            raise FunctionGatewayError(
                "FUNCTION_ENVELOPE_INVALID",
                "The function-call envelope has unknown, missing, or invalid fields.",
                retryable=False,
                next_action="Return only call_id, name, and object arguments with exact types.",
            ) from error

    def _attest(self, catalog_sha256: str) -> str:
        return hmac.new(
            self._attestation_key,
            catalog_sha256.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _context_sha256(context: ToolInvocationContext) -> str:
        return canonical_sha256(
            {
                "schema_version": context.schema_version,
                "task_id": str(context.task_id),
                "run_id": str(context.run_id),
                "scope": context.scope.model_dump(mode="json"),
                "request_id": context.request_id,
                "policy_version": context.policy_version,
                "expected_registry_version": context.expected_registry_version,
                "allowed_tools": sorted(context.allowed_tools),
                "granted_permissions": sorted(context.granted_permissions),
                "allowed_secret_purposes": sorted(context.allowed_secret_purposes),
                "allowed_data_destinations": sorted(context.allowed_data_destinations),
                "approved_call_sha256s": sorted(context.approved_call_sha256s),
                "allow_network": context.allow_network,
            }
        )

    @staticmethod
    def _raw_sha256(raw_call: object) -> str:
        if isinstance(raw_call, bytes):
            encoded = raw_call
        elif isinstance(raw_call, str):
            encoded = raw_call.encode("utf-8", errors="surrogatepass")
        else:
            encoded = type(raw_call).__qualname__.encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _record(
        self,
        context: ToolInvocationContext,
        *,
        target_id: str,
        action: str,
        decision: str,
        outcome: AuditOutcome,
        input_sha256: str,
        output_sha256: str,
    ) -> None:
        self._audit.record(
            AuditRecord(
                event_id=uuid4(),
                scope=context.scope,
                kind=AuditKind.TOOL,
                action=action,
                target_type="function",
                target_id=target_id,
                task_id=context.task_id,
                policy_version=context.policy_version,
                decision=decision,
                outcome=outcome,
                input_sha256=input_sha256,
                output_sha256=output_sha256,
                request_id=context.request_id,
                occurred_at=self._clock(),
            )
        )

    @staticmethod
    def _deny(code: str, message: str) -> NoReturn:
        raise FunctionGatewayError(
            code,
            message,
            retryable=False,
            next_action="Reload the current authorized catalog and correct the function call.",
        )


def _function_name(tool_name: str, tool_version: str) -> str:
    base = re.sub(r"[^a-z0-9_]", "_", tool_name)
    digest = canonical_sha256({"tool_name": tool_name, "tool_version": tool_version})[:12]
    return f"{base[:51]}_{digest}"


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(key)
        result[key] = value
    return result


def _reject_non_finite(value: str) -> NoReturn:
    raise _NonFiniteJsonNumber(value)


def _invalid_schema_references(schema: Mapping[str, Any]) -> tuple[str, ...]:
    invalid: set[str] = set()

    def visit(current: object) -> None:
        if isinstance(current, Mapping):
            for keyword in ("$ref", "$dynamicRef", "$recursiveRef"):
                if keyword in current:
                    reference = current[keyword]
                    if not isinstance(reference, str) or not _resolves_local_pointer(
                        schema, reference
                    ):
                        invalid.add(f"{keyword}:{reference}")
            for nested in current.values():
                visit(nested)
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            for nested in current:
                visit(nested)

    visit(schema)
    return tuple(sorted(invalid))


def _resolves_local_pointer(schema: Mapping[str, Any], reference: str) -> bool:
    if reference == "#":
        return True
    if not reference.startswith("#/"):
        return False
    current: object = schema
    for encoded_token in reference[2:].split("/"):
        if re.search(r"~(?:[^01]|$)", encoded_token):
            return False
        token = encoded_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                return False
            current = current[token]
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                return False
            index = int(token)
            if index >= len(current):
                return False
            current = current[index]
        else:
            return False
    return True
