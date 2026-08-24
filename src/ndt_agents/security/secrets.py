"""Scoped short-lived secret leases with explicit rotation and revocation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from enum import StrEnum
from threading import RLock
from typing import Protocol

from pydantic import SecretStr

from ndt_agents.observability.audit import AuditOutcome
from ndt_agents.security.audit import SecurityAuditHook, metadata_sha256
from ndt_agents.security.models import (
    SecretLease,
    SecretRef,
    SecretSelector,
    SecurityContext,
    SecurityError,
)


class _SecretState(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class SecretProvider(Protocol):
    def current_ref(self, selector: SecretSelector) -> SecretRef: ...

    def reveal(self, ref: SecretRef) -> SecretStr: ...

    def rotate(self, selector: SecretSelector, version: str, value: SecretStr) -> SecretRef: ...

    def revoke(self, ref: SecretRef) -> None: ...


class InMemorySecretProvider:
    """Local test provider; never a production secret store."""

    def __init__(self) -> None:
        self._values: dict[SecretRef, SecretStr] = {}
        self._states: dict[SecretRef, _SecretState] = {}
        self._current: dict[SecretSelector, SecretRef] = {}
        self._available = True
        self._lock = RLock()

    def set_available(self, available: bool) -> None:
        with self._lock:
            self._available = available

    def register_test_secret(
        self, selector: SecretSelector, *, version: str, value: SecretStr
    ) -> SecretRef:
        with self._lock:
            self._ensure_available()
            self._validate_value(value)
            if selector in self._current:
                raise SecurityError(
                    code="SECRET_VERSION_STALE",
                    message="The secret selector already has an active version.",
                    retryable=False,
                    next_action="Rotate the existing secret instead of registering another root.",
                )
            ref = SecretRef(**selector.model_dump(), version=version)
            self._values[ref] = value
            self._states[ref] = _SecretState.ACTIVE
            self._current[selector] = ref
            return ref

    def current_ref(self, selector: SecretSelector) -> SecretRef:
        with self._lock:
            self._ensure_available()
            ref = self._current.get(selector)
            if ref is None:
                raise SecurityError(
                    code="SECRET_NOT_FOUND",
                    message="The requested secret reference does not exist.",
                    retryable=False,
                    next_action="Provision the approved secret reference before retrying.",
                )
            if self._states[ref] is _SecretState.REVOKED:
                raise SecurityError(
                    code="SECRET_REVOKED",
                    message="The active secret version is revoked.",
                    retryable=False,
                    next_action="Rotate to an approved new version.",
                )
            return ref

    def reveal(self, ref: SecretRef) -> SecretStr:
        with self._lock:
            self._ensure_available()
            current = self._current.get(ref.selector)
            if current is None:
                raise SecurityError(
                    code="SECRET_NOT_FOUND",
                    message="The requested secret reference does not exist.",
                    retryable=False,
                    next_action="Provision the approved secret reference before retrying.",
                )
            if ref != current:
                raise SecurityError(
                    code="SECRET_VERSION_STALE",
                    message="The requested secret version is stale.",
                    retryable=False,
                    next_action="Resolve the current approved secret version.",
                )
            if self._states[ref] is _SecretState.REVOKED:
                raise SecurityError(
                    code="SECRET_REVOKED",
                    message="The requested secret version is revoked.",
                    retryable=False,
                    next_action="Rotate to an approved new version.",
                )
            return self._values[ref]

    def rotate(self, selector: SecretSelector, version: str, value: SecretStr) -> SecretRef:
        with self._lock:
            current = self.current_ref(selector)
            self._validate_value(value)
            candidate = SecretRef(**selector.model_dump(), version=version)
            if candidate in self._values:
                raise SecurityError(
                    code="SECRET_VERSION_STALE",
                    message="The requested secret version already exists.",
                    retryable=False,
                    next_action="Use a new immutable secret version.",
                )
            self._states[current] = _SecretState.REVOKED
            self._values[candidate] = value
            self._states[candidate] = _SecretState.ACTIVE
            self._current[selector] = candidate
            return candidate

    def revoke(self, ref: SecretRef) -> None:
        with self._lock:
            self._ensure_available()
            if ref not in self._states:
                raise SecurityError(
                    code="SECRET_NOT_FOUND",
                    message="The requested secret reference does not exist.",
                    retryable=False,
                    next_action="Verify the approved secret reference.",
                )
            self._states[ref] = _SecretState.REVOKED

    def _ensure_available(self) -> None:
        if not self._available:
            raise SecurityError(
                code="SECRET_PROVIDER_UNAVAILABLE",
                message="The secret provider is unavailable.",
                retryable=True,
                next_action="Restore the approved provider and retry without plaintext fallback.",
            )

    @staticmethod
    def _validate_value(value: SecretStr) -> None:
        length = len(value.get_secret_value())
        if not 1 <= length <= 16_384:
            raise SecurityError(
                code="SECRET_VALUE_INVALID",
                message="The secret value is empty or exceeds the bounded lease size.",
                retryable=False,
                next_action="Provision a non-empty bounded secret through the approved provider.",
            )


class SecretManager:
    """Authorize, lease, rotate, revoke, and audit provider-backed secrets."""

    def __init__(
        self,
        provider: SecretProvider,
        audit: SecurityAuditHook,
        *,
        clock: Callable[[], datetime],
        lease_seconds: int = 60,
    ) -> None:
        if not 1 <= lease_seconds <= 300:
            raise ValueError("secret lease must be between 1 and 300 seconds")
        self._provider = provider
        self._audit = audit
        self._clock = clock
        self._lease_seconds = lease_seconds

    def resolve_current(self, context: SecurityContext, selector: SecretSelector) -> SecretLease:
        input_sha256 = metadata_sha256(selector.model_dump(mode="json"))
        try:
            self._authorize(context, selector)
            ref = self._provider.current_ref(selector)
            value = self._provider.reveal(ref)
            issued_at = self._clock()
            lease = SecretLease(
                ref=ref,
                accessor_user_id=context.scope.user_id,
                permission_version=context.scope.permission_version,
                policy_version=context.policy_version,
                issued_at=issued_at,
                expires_at=issued_at + timedelta(seconds=self._lease_seconds),
                value=value,
            )
        except SecurityError as error:
            self._record_denial(context, selector, "security.secret.resolve", input_sha256, error)
            raise
        self._audit.record(
            context=context,
            action="security.secret.resolve",
            target_type="security.secret",
            target_id=selector.secret_id,
            decision="ALLOW",
            outcome=AuditOutcome.SUCCESS,
            input_sha256=input_sha256,
            output_sha256=metadata_sha256(
                {"ref": ref.model_dump(mode="json"), "expires_at": lease.expires_at.isoformat()}
            ),
        )
        return lease

    def read(self, context: SecurityContext, lease: SecretLease) -> SecretStr:
        selector = lease.ref.selector
        input_sha256 = metadata_sha256(lease.model_dump(mode="json"))
        try:
            self._authorize(context, selector)
            now = self._clock()
            if (
                lease.accessor_user_id != context.scope.user_id
                or lease.permission_version != context.scope.permission_version
                or lease.policy_version != context.policy_version
            ):
                raise self._scope_error()
            if now >= lease.expires_at:
                raise SecurityError(
                    code="SECRET_LEASE_EXPIRED",
                    message="The secret lease has expired.",
                    retryable=True,
                    next_action="Resolve a new short-lived lease.",
                )
            value = self._provider.reveal(lease.ref)
        except SecurityError as error:
            self._record_denial(context, selector, "security.secret.use", input_sha256, error)
            raise
        self._audit.record(
            context=context,
            action="security.secret.use",
            target_type="security.secret",
            target_id=selector.secret_id,
            decision="ALLOW",
            outcome=AuditOutcome.SUCCESS,
            input_sha256=input_sha256,
            output_sha256=metadata_sha256({"ref": lease.ref.model_dump(mode="json"), "used": True}),
        )
        return value

    def rotate(
        self,
        context: SecurityContext,
        selector: SecretSelector,
        *,
        version: str,
        value: SecretStr,
    ) -> SecretRef:
        input_sha256 = metadata_sha256(
            {"selector": selector.model_dump(mode="json"), "version": version}
        )
        try:
            self._authorize(context, selector)
            self._record_authorized(context, selector, "security.secret.rotate", input_sha256)
            ref = self._provider.rotate(selector, version, value)
        except SecurityError as error:
            self._record_denial(context, selector, "security.secret.rotate", input_sha256, error)
            raise
        self._audit.record(
            context=context,
            action="security.secret.rotate",
            target_type="security.secret",
            target_id=selector.secret_id,
            decision="ALLOW",
            outcome=AuditOutcome.SUCCESS,
            input_sha256=input_sha256,
            output_sha256=metadata_sha256(ref.model_dump(mode="json")),
        )
        return ref

    def revoke(self, context: SecurityContext, ref: SecretRef) -> None:
        selector = ref.selector
        input_sha256 = metadata_sha256(ref.model_dump(mode="json"))
        try:
            self._authorize(context, selector)
            self._record_authorized(context, selector, "security.secret.revoke", input_sha256)
            self._provider.revoke(ref)
        except SecurityError as error:
            self._record_denial(context, selector, "security.secret.revoke", input_sha256, error)
            raise
        self._audit.record(
            context=context,
            action="security.secret.revoke",
            target_type="security.secret",
            target_id=selector.secret_id,
            decision="ALLOW",
            outcome=AuditOutcome.SUCCESS,
            input_sha256=input_sha256,
            output_sha256=metadata_sha256({"state": "REVOKED", "version": ref.version}),
        )

    @staticmethod
    def _scope_error() -> SecurityError:
        return SecurityError(
            code="SECURITY_SCOPE_MISMATCH",
            message="The secret reference is outside the authorized security scope.",
            retryable=False,
            next_action="Use the exact authorized environment, tenant, project, user, and purpose.",
        )

    def _authorize(self, context: SecurityContext, selector: SecretSelector) -> None:
        scope = context.scope
        if (
            context.environment != selector.environment
            or scope.tenant_id != selector.tenant_id
            or scope.project_id != selector.project_id
            or selector.purpose not in context.allowed_secret_purposes
        ):
            raise self._scope_error()

    def _record_denial(
        self,
        context: SecurityContext,
        selector: SecretSelector,
        action: str,
        input_sha256: str,
        error: SecurityError,
    ) -> None:
        self._audit.record(
            context=context,
            action=action,
            target_type="security.secret",
            target_id=selector.secret_id,
            decision="DENY",
            outcome=AuditOutcome.DENIED,
            input_sha256=input_sha256,
            output_sha256=metadata_sha256({"error_code": error.code}),
        )

    def _record_authorized(
        self,
        context: SecurityContext,
        selector: SecretSelector,
        action: str,
        input_sha256: str,
    ) -> None:
        self._audit.record(
            context=context,
            action=action,
            target_type="security.secret",
            target_id=selector.secret_id,
            decision="ALLOW",
            outcome=AuditOutcome.PARTIAL,
            input_sha256=input_sha256,
            output_sha256=metadata_sha256({"state": "AUTHORIZED_NOT_COMPLETED"}),
        )
