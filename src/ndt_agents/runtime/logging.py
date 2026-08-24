"""Structured JSON logging with request correlation and credential redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Final, TextIO

_REQUEST_ID: ContextVar[str | None] = ContextVar("ndt_request_id", default=None)
_CREDENTIAL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(authorization|password|secret|token|api[_-]?key)\s*[:=]\s*"
    r"(?:Bearer\s+)?[^\s,;]+"
)
_URL_CREDENTIAL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(https?|postgresql(?:\+asyncpg)?|rediss?)://[^\s/@:]+:[^\s/@]+@"
)
_STRUCTURED_FIELDS: Final[tuple[str, ...]] = (
    "event",
    "method",
    "path",
    "status_code",
    "duration_ms",
    "error_code",
)


def bind_request_id(request_id: str) -> Token[str | None]:
    """Bind correlation state for the current asynchronous execution context."""

    return _REQUEST_ID.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the prior correlation state."""

    _REQUEST_ID.reset(token)


def current_request_id() -> str | None:
    """Return the request ID bound to the current execution context."""

    return _REQUEST_ID.get()


def redact_credentials(value: str) -> str:
    """Redact common inline credential forms from application log text."""

    without_url_credentials = _URL_CREDENTIAL_PATTERN.sub(
        lambda match: f"{match.group(1)}://[REDACTED]@", value
    )
    return _CREDENTIAL_PATTERN.sub(
        lambda match: f"{match.group(1)}=[REDACTED]", without_url_credentials
    )


class JsonFormatter(logging.Formatter):
    """Emit a stable JSON object and avoid serializing arbitrary LogRecord fields."""

    def __init__(self, service_name: str, environment: str) -> None:
        super().__init__()
        self._service_name = service_name
        self._environment = environment

    def format(self, record: logging.LogRecord) -> str:
        request_id = getattr(record, "request_id", None) or current_request_id()
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "service": self._service_name,
            "environment": self._environment,
            "message": redact_credentials(record.getMessage()),
        }
        if request_id is not None:
            payload["request_id"] = request_id
        for field in _STRUCTURED_FIELDS:
            field_value = getattr(record, field, None)
            if field_value is not None:
                payload[field] = (
                    redact_credentials(field_value) if isinstance(field_value, str) else field_value
                )
        if record.exc_info and record.exc_info[0]:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(
    *, service_name: str, environment: str, level: str, stream: TextIO | None = None
) -> None:
    """Configure one root JSON handler for application and ASGI server logs."""

    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter(service_name=service_name, environment=environment))
    root = logging.getLogger()
    for existing in root.handlers:
        existing.close()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
