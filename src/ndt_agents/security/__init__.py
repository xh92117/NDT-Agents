"""Provider-neutral S1 platform security controls."""

from ndt_agents.security.audit import AuditSecurityHook, SecurityAuditHook
from ndt_agents.security.crypto import EnvelopeEncryptionService, InMemoryKeyProvider
from ndt_agents.security.models import (
    EncryptedEnvelope,
    KeyRef,
    KeySelector,
    KeyState,
    SecretLease,
    SecretRef,
    SecretSelector,
    SecurityContext,
    SecurityEnvironment,
    SecurityError,
)
from ndt_agents.security.secrets import InMemorySecretProvider, SecretManager
from ndt_agents.security.transport import TransportKind, TransportSecurityService

__all__ = (
    "AuditSecurityHook",
    "EncryptedEnvelope",
    "EnvelopeEncryptionService",
    "InMemoryKeyProvider",
    "InMemorySecretProvider",
    "KeyRef",
    "KeySelector",
    "KeyState",
    "SecretLease",
    "SecretManager",
    "SecretRef",
    "SecretSelector",
    "SecurityAuditHook",
    "SecurityContext",
    "SecurityEnvironment",
    "SecurityError",
    "TransportKind",
    "TransportSecurityService",
)
