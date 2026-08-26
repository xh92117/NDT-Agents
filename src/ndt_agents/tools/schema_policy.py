"""Shared deterministic JSON Schema security policy."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

PLAINTEXT_SECRET_FIELDS = frozenset(
    {
        "access_key",
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "password",
        "private_key",
        "secret",
        "token",
    }
)


def plaintext_secret_fields(value: object) -> frozenset[str]:
    """Return normalized sensitive property names found anywhere in a JSON Schema."""

    found: set[str] = set()

    def visit(current: object) -> None:
        if isinstance(current, Mapping):
            properties = current.get("properties")
            if isinstance(properties, Mapping):
                for name in properties:
                    normalized = str(name).lower().replace("-", "_")
                    if normalized in PLAINTEXT_SECRET_FIELDS:
                        found.add(str(name))
            for nested in current.values():
                visit(nested)
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            for nested in current:
                visit(nested)

    visit(value)
    return frozenset(found)
