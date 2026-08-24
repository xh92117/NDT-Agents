"""Hash-only adapter from platform security decisions to S1 audit events."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Protocol
from uuid import UUID

from ndt_agents.observability.audit import (
    AuditError,
    AuditKind,
    AuditOutcome,
    AuditRecord,
    AuditService,
)
from ndt_agents.observability.tracing import TraceError
from ndt_agents.security.models import SecurityContext, SecurityError


def metadata_sha256(metadata: Mapping[str, object]) -> str:
    encoded = json.dumps(
        metadata,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class SecurityAuditHook(Protocol):
    def record(
        self,
        *,
        context: SecurityContext,
        action: str,
        target_type: str,
        target_id: str,
        decision: str,
        outcome: AuditOutcome,
        input_sha256: str,
        output_sha256: str,
    ) -> None: ...


class AuditSecurityHook:
    """Create mandatory SECURITY events without accepting raw values."""

    def __init__(
        self,
        audit: AuditService,
        *,
        clock: Callable[[], datetime],
        event_id_factory: Callable[[], UUID],
    ) -> None:
        self._audit = audit
        self._clock = clock
        self._event_id_factory = event_id_factory

    def record(
        self,
        *,
        context: SecurityContext,
        action: str,
        target_type: str,
        target_id: str,
        decision: str,
        outcome: AuditOutcome,
        input_sha256: str,
        output_sha256: str,
    ) -> None:
        try:
            self._audit.record(
                AuditRecord(
                    event_id=self._event_id_factory(),
                    scope=context.scope,
                    kind=AuditKind.SECURITY,
                    action=action,
                    target_type=target_type,
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
        except (AuditError, TraceError, ValueError) as error:
            raise SecurityError(
                code="SECURITY_AUDIT_FAILED",
                message="The mandatory security audit event could not be preserved.",
                retryable=True,
                next_action="Restore audit and trace services before retrying the operation.",
            ) from error
