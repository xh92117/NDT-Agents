"""AES-256-GCM envelope encryption with scoped key rotation and revocation."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from threading import RLock
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretBytes

from ndt_agents.observability.audit import AuditOutcome
from ndt_agents.security.audit import SecurityAuditHook, metadata_sha256
from ndt_agents.security.models import (
    EncryptedEnvelope,
    KeyRef,
    KeySelector,
    KeyState,
    SecurityContext,
    SecurityError,
)

_AAD_CONTEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


@dataclass(frozen=True, slots=True)
class _ProviderCiphertext:
    key_ref: KeyRef
    nonce: bytes
    ciphertext: bytes


class KeyProvider(Protocol):
    def encrypt(
        self, selector: KeySelector, plaintext: bytes, aad: bytes
    ) -> _ProviderCiphertext: ...

    def decrypt(self, ref: KeyRef, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes: ...

    def rotate(self, selector: KeySelector, version: str, material: SecretBytes) -> KeyRef: ...

    def revoke(self, ref: KeyRef) -> None: ...


class InMemoryKeyProvider:
    """AES-GCM test provider; raw material never leaves its encrypt/decrypt interface."""

    def __init__(self) -> None:
        self._keys: dict[KeyRef, SecretBytes] = {}
        self._states: dict[KeyRef, KeyState] = {}
        self._active: dict[KeySelector, KeyRef] = {}
        self._available = True
        self._lock = RLock()

    def set_available(self, available: bool) -> None:
        with self._lock:
            self._available = available

    def register_test_key(
        self, selector: KeySelector, *, version: str, material: SecretBytes
    ) -> KeyRef:
        with self._lock:
            self._ensure_available()
            if selector in self._active:
                raise self._version_error("The key selector already has an active version.")
            self._validate_material(material)
            ref = KeyRef(**selector.model_dump(), version=version)
            self._keys[ref] = material
            self._states[ref] = KeyState.ACTIVE
            self._active[selector] = ref
            return ref

    def encrypt(self, selector: KeySelector, plaintext: bytes, aad: bytes) -> _ProviderCiphertext:
        with self._lock:
            self._ensure_available()
            ref = self._active_ref(selector)
            if self._states[ref] is not KeyState.ACTIVE:
                raise self._revoked()
            nonce = os.urandom(12)
            ciphertext = AESGCM(self._keys[ref].get_secret_value()).encrypt(nonce, plaintext, aad)
            return _ProviderCiphertext(key_ref=ref, nonce=nonce, ciphertext=ciphertext)

    def decrypt(self, ref: KeyRef, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
        with self._lock:
            self._ensure_available()
            material = self._keys.get(ref)
            if material is None:
                raise SecurityError(
                    code="KEY_NOT_FOUND",
                    message="The referenced encryption key does not exist.",
                    retryable=False,
                    next_action="Restore the approved key version or verified backup.",
                )
            if self._states[ref] is KeyState.REVOKED:
                raise self._revoked()
            try:
                return AESGCM(material.get_secret_value()).decrypt(nonce, ciphertext, aad)
            except (InvalidTag, ValueError):
                raise SecurityError(
                    code="DECRYPTION_FAILED",
                    message="The encrypted envelope failed authenticated decryption.",
                    retryable=False,
                    next_action="Quarantine it and restore verified encrypted evidence.",
                ) from None

    def rotate(self, selector: KeySelector, version: str, material: SecretBytes) -> KeyRef:
        with self._lock:
            self._ensure_available()
            self._validate_material(material)
            current = self._active_ref(selector)
            candidate = KeyRef(**selector.model_dump(), version=version)
            if candidate in self._keys:
                raise self._version_error("The requested key version already exists.")
            self._states[current] = KeyState.DECRYPT_ONLY
            self._keys[candidate] = material
            self._states[candidate] = KeyState.ACTIVE
            self._active[selector] = candidate
            return candidate

    def revoke(self, ref: KeyRef) -> None:
        with self._lock:
            self._ensure_available()
            if ref not in self._states:
                raise SecurityError(
                    code="KEY_NOT_FOUND",
                    message="The referenced encryption key does not exist.",
                    retryable=False,
                    next_action="Verify the approved key reference.",
                )
            self._states[ref] = KeyState.REVOKED

    def state(self, ref: KeyRef) -> KeyState:
        with self._lock:
            if ref not in self._states:
                raise SecurityError(
                    code="KEY_NOT_FOUND",
                    message="The referenced encryption key does not exist.",
                    retryable=False,
                    next_action="Verify the approved key reference.",
                )
            return self._states[ref]

    def _active_ref(self, selector: KeySelector) -> KeyRef:
        ref = self._active.get(selector)
        if ref is None:
            raise SecurityError(
                code="KEY_NOT_FOUND",
                message="No active encryption key exists for the requested scope and purpose.",
                retryable=False,
                next_action="Provision an approved key before retrying.",
            )
        return ref

    @staticmethod
    def _validate_material(material: SecretBytes) -> None:
        if len(material.get_secret_value()) != 32:
            raise SecurityError(
                code="ENCRYPTION_FAILED",
                message="The AES-256 key material has an invalid length.",
                retryable=False,
                next_action="Provision an approved 256-bit key.",
            )

    @staticmethod
    def _version_error(message: str) -> SecurityError:
        return SecurityError(
            code="KEY_VERSION_STALE",
            message=message,
            retryable=False,
            next_action="Use a new immutable key version.",
        )

    @staticmethod
    def _revoked() -> SecurityError:
        return SecurityError(
            code="KEY_REVOKED",
            message="The referenced encryption key is revoked.",
            retryable=False,
            next_action="Restore from an approved key version or verified backup.",
        )

    def _ensure_available(self) -> None:
        if not self._available:
            raise SecurityError(
                code="KEY_PROVIDER_UNAVAILABLE",
                message="The key provider is unavailable.",
                retryable=True,
                next_action="Restore it and retry without plaintext fallback.",
            )


class EnvelopeEncryptionService:
    """Authorize and audit scoped envelope encryption over a key provider port."""

    def __init__(self, provider: KeyProvider, audit: SecurityAuditHook) -> None:
        self._provider = provider
        self._audit = audit

    def encrypt(
        self,
        context: SecurityContext,
        selector: KeySelector,
        plaintext: bytes,
        *,
        aad_context: str,
    ) -> EncryptedEnvelope:
        input_sha256 = metadata_sha256(
            {
                "selector": selector.model_dump(mode="json"),
                "aad_context_sha256": self._sha256(aad_context.encode("utf-8")),
            }
        )
        try:
            self._authorize(context, selector)
            aad = self._aad(context, selector, aad_context, failure_code="ENCRYPTION_FAILED")
            encrypted = self._provider.encrypt(selector, plaintext, aad)
            envelope = EncryptedEnvelope(
                key_ref=encrypted.key_ref,
                nonce_b64u=self._encode(encrypted.nonce),
                ciphertext_b64u=self._encode(encrypted.ciphertext),
                aad_sha256=self._sha256(aad),
            )
        except SecurityError as error:
            self._record_denial(context, selector, "security.key.encrypt", input_sha256, error)
            raise
        self._audit.record(
            context=context,
            action="security.key.encrypt",
            target_type="security.key",
            target_id=selector.key_id,
            decision="ALLOW",
            outcome=AuditOutcome.SUCCESS,
            input_sha256=input_sha256,
            output_sha256=metadata_sha256(
                {
                    "key_ref": envelope.key_ref.model_dump(mode="json"),
                    "aad_sha256": envelope.aad_sha256,
                }
            ),
        )
        return envelope

    def decrypt(
        self,
        context: SecurityContext,
        envelope: EncryptedEnvelope,
        *,
        aad_context: str,
    ) -> bytes:
        selector = envelope.key_ref.selector
        input_sha256 = metadata_sha256(
            {
                "key_ref": envelope.key_ref.model_dump(mode="json"),
                "aad_sha256": envelope.aad_sha256,
                "aad_context_sha256": self._sha256(aad_context.encode("utf-8")),
            }
        )
        try:
            self._authorize(context, selector)
            aad = self._aad(context, selector, aad_context, failure_code="DECRYPTION_FAILED")
            if not hmac.compare_digest(envelope.aad_sha256, self._sha256(aad)):
                raise SecurityError(
                    code="DECRYPTION_FAILED",
                    message="The encrypted envelope scope or authenticated context is invalid.",
                    retryable=False,
                    next_action="Use the exact authorized scope and authenticated context.",
                )
            plaintext = self._provider.decrypt(
                envelope.key_ref,
                self._decode(envelope.nonce_b64u),
                self._decode(envelope.ciphertext_b64u),
                aad,
            )
        except SecurityError as error:
            self._record_denial(context, selector, "security.key.decrypt", input_sha256, error)
            raise
        self._audit.record(
            context=context,
            action="security.key.decrypt",
            target_type="security.key",
            target_id=selector.key_id,
            decision="ALLOW",
            outcome=AuditOutcome.SUCCESS,
            input_sha256=input_sha256,
            output_sha256=metadata_sha256(
                {"key_version": envelope.key_ref.version, "decrypted": True}
            ),
        )
        return plaintext

    def rotate(
        self,
        context: SecurityContext,
        selector: KeySelector,
        *,
        version: str,
        material: SecretBytes,
    ) -> KeyRef:
        input_sha256 = metadata_sha256(
            {"selector": selector.model_dump(mode="json"), "version": version}
        )
        try:
            self._authorize(context, selector)
            self._record_authorized(context, selector, "security.key.rotate", input_sha256)
            ref = self._provider.rotate(selector, version, material)
        except SecurityError as error:
            self._record_denial(context, selector, "security.key.rotate", input_sha256, error)
            raise
        self._audit.record(
            context=context,
            action="security.key.rotate",
            target_type="security.key",
            target_id=selector.key_id,
            decision="ALLOW",
            outcome=AuditOutcome.SUCCESS,
            input_sha256=input_sha256,
            output_sha256=metadata_sha256(ref.model_dump(mode="json")),
        )
        return ref

    def revoke(self, context: SecurityContext, ref: KeyRef) -> None:
        selector = ref.selector
        input_sha256 = metadata_sha256(ref.model_dump(mode="json"))
        try:
            self._authorize(context, selector)
            self._record_authorized(context, selector, "security.key.revoke", input_sha256)
            self._provider.revoke(ref)
        except SecurityError as error:
            self._record_denial(context, selector, "security.key.revoke", input_sha256, error)
            raise
        self._audit.record(
            context=context,
            action="security.key.revoke",
            target_type="security.key",
            target_id=selector.key_id,
            decision="ALLOW",
            outcome=AuditOutcome.SUCCESS,
            input_sha256=input_sha256,
            output_sha256=metadata_sha256({"state": "REVOKED", "version": ref.version}),
        )

    @staticmethod
    def _aad(
        context: SecurityContext,
        selector: KeySelector,
        aad_context: str,
        *,
        failure_code: str,
    ) -> bytes:
        if _AAD_CONTEXT.fullmatch(aad_context) is None:
            raise SecurityError(
                code=failure_code,
                message="The authenticated encryption context is invalid.",
                retryable=False,
                next_action="Use a stable bounded context identifier.",
            )
        payload = {
            "environment": context.environment.value,
            "tenant_id": str(context.scope.tenant_id),
            "project_id": str(context.scope.project_id),
            "purpose": selector.purpose,
            "context": aad_context,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def _scope_error() -> SecurityError:
        return SecurityError(
            code="SECURITY_SCOPE_MISMATCH",
            message="The key reference is outside the authorized security scope.",
            retryable=False,
            next_action="Use the exact authorized environment, tenant, project, and purpose.",
        )

    def _authorize(self, context: SecurityContext, selector: KeySelector) -> None:
        if (
            context.environment != selector.environment
            or context.scope.tenant_id != selector.tenant_id
            or context.scope.project_id != selector.project_id
            or selector.purpose not in context.allowed_key_purposes
        ):
            raise self._scope_error()

    def _record_denial(
        self,
        context: SecurityContext,
        selector: KeySelector,
        action: str,
        input_sha256: str,
        error: SecurityError,
    ) -> None:
        self._audit.record(
            context=context,
            action=action,
            target_type="security.key",
            target_id=selector.key_id,
            decision="DENY",
            outcome=AuditOutcome.DENIED,
            input_sha256=input_sha256,
            output_sha256=metadata_sha256({"error_code": error.code}),
        )

    def _record_authorized(
        self,
        context: SecurityContext,
        selector: KeySelector,
        action: str,
        input_sha256: str,
    ) -> None:
        self._audit.record(
            context=context,
            action=action,
            target_type="security.key",
            target_id=selector.key_id,
            decision="ALLOW",
            outcome=AuditOutcome.PARTIAL,
            input_sha256=input_sha256,
            output_sha256=metadata_sha256({"state": "AUTHORIZED_NOT_COMPLETED"}),
        )

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    @staticmethod
    def _decode(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        try:
            return base64.b64decode(value + padding, altchars=b"-_", validate=True)
        except (binascii.Error, ValueError):
            raise SecurityError(
                code="DECRYPTION_FAILED",
                message="The encrypted envelope encoding is invalid.",
                retryable=False,
                next_action="Use an unmodified versioned encrypted envelope.",
            ) from None

    @staticmethod
    def _sha256(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()
