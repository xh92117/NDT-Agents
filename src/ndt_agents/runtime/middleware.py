"""Request correlation and minimal response hardening for the API scaffold."""

from __future__ import annotations

import logging
import re
from time import perf_counter
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from ndt_agents.runtime.logging import bind_request_id, reset_request_id

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_LOGGER = logging.getLogger(__name__)


def safe_request_id(candidate: str | None) -> str:
    """Accept a bounded safe correlation ID or create a local opaque ID."""

    if candidate is not None and _REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return uuid4().hex


def apply_response_headers(response: Response, request_id: str) -> None:
    """Apply headers shared by successful and failed API responses."""

    response.headers["x-request-id"] = request_id
    response.headers["cache-control"] = "no-store"
    response.headers["x-content-type-options"] = "nosniff"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind request correlation and record one bounded completion event."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = safe_request_id(request.headers.get("x-request-id"))
        request.state.request_id = request_id
        token = bind_request_id(request_id)
        started = perf_counter()
        try:
            response = await call_next(request)
            apply_response_headers(response, request_id)
            _LOGGER.info(
                "request completed",
                extra={
                    "event": "request_completed",
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": max(0, round((perf_counter() - started) * 1000)),
                },
            )
            return response
        finally:
            reset_request_id(token)
