"""Deterministic TLS policy validation without opening a network connection."""

from __future__ import annotations

import hashlib
import ipaddress
from enum import StrEnum
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict

from ndt_agents.observability.audit import AuditOutcome
from ndt_agents.security.audit import SecurityAuditHook, metadata_sha256
from ndt_agents.security.models import SecurityContext, SecurityEnvironment, SecurityError


class TransportKind(StrEnum):
    HTTPS = "HTTPS"
    POSTGRES = "POSTGRES"
    REDIS = "REDIS"


class TransportDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: TransportKind
    encrypted: bool
    minimum_tls_version: str
    certificate_validation: bool
    loopback_exception: bool


class TransportSecurityService:
    """Apply one transport policy and audit every allow or denial."""

    def __init__(self, audit: SecurityAuditHook) -> None:
        self._audit = audit

    def validate(
        self,
        context: SecurityContext,
        kind: TransportKind,
        endpoint: str,
    ) -> TransportDecision:
        endpoint_sha256 = hashlib.sha256(endpoint.encode("utf-8")).hexdigest()
        target_id = f"endpoint-{endpoint_sha256[:32]}"
        input_sha256 = metadata_sha256({"kind": kind.value, "endpoint_sha256": endpoint_sha256})
        try:
            decision = self._validate(context.environment, kind, endpoint)
        except SecurityError as error:
            self._audit.record(
                context=context,
                action="security.transport.validate",
                target_type="security.transport",
                target_id=target_id,
                decision="DENY",
                outcome=AuditOutcome.DENIED,
                input_sha256=input_sha256,
                output_sha256=metadata_sha256({"error_code": error.code}),
            )
            raise
        self._audit.record(
            context=context,
            action="security.transport.validate",
            target_type="security.transport",
            target_id=target_id,
            decision="ALLOW",
            outcome=AuditOutcome.SUCCESS,
            input_sha256=input_sha256,
            output_sha256=metadata_sha256(decision.model_dump(mode="json")),
        )
        return decision

    @classmethod
    def _validate(
        cls,
        environment: SecurityEnvironment,
        kind: TransportKind,
        endpoint: str,
    ) -> TransportDecision:
        if (
            not endpoint
            or len(endpoint) > 2048
            or "\\" in endpoint
            or any(ord(character) <= 32 or ord(character) == 127 for character in endpoint)
        ):
            raise cls._denied()
        try:
            parsed = urlsplit(endpoint)
            host = parsed.hostname
            port = parsed.port
        except ValueError:
            raise cls._denied() from None
        if (
            host is None
            or (port is not None and not 1 <= port <= 65_535)
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise cls._denied()
        query = parse_qs(parsed.query, keep_blank_values=True)
        loopback_exception = environment in {
            SecurityEnvironment.LOCAL,
            SecurityEnvironment.CI,
        } and cls._is_loopback(host)

        if kind is TransportKind.HTTPS:
            encrypted = parsed.scheme == "https"
            query_denies_verification = any(
                value.lower() in {"0", "false", "no", "none"}
                for key in ("verify", "ssl_verify", "cert_reqs")
                for value in query.get(key, ())
            )
            valid = (encrypted and not query_denies_verification) or (
                loopback_exception and parsed.scheme == "http"
            )
        elif kind is TransportKind.POSTGRES:
            encrypted = query.get("sslmode") == ["verify-full"]
            valid = parsed.scheme == "postgresql+asyncpg" and (
                encrypted or (loopback_exception and "sslmode" not in query)
            )
        else:
            encrypted = parsed.scheme == "rediss" and query.get("ssl_cert_reqs") == ["required"]
            valid = encrypted or (loopback_exception and parsed.scheme == "redis")

        if not valid:
            raise cls._denied()
        return TransportDecision(
            kind=kind,
            encrypted=encrypted,
            minimum_tls_version="TLS1.2",
            certificate_validation=encrypted,
            loopback_exception=loopback_exception and not encrypted,
        )

    @staticmethod
    def _is_loopback(host: str) -> bool:
        if host.lower() == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    @staticmethod
    def _denied() -> SecurityError:
        return SecurityError(
            code="TLS_POLICY_DENIED",
            message="The endpoint violates the active transport security policy.",
            retryable=False,
            next_action="Use certificate-validated TLS or an explicit loopback local/CI endpoint.",
        )
