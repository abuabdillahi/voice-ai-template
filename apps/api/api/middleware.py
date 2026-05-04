"""ASGI middleware for the FastAPI app.

Currently exposes the request-id middleware. Each incoming request is
assigned a UUID v4 (or echoed from a client-provided ``X-Request-ID``
header) which is bound to the structlog context for the duration of
the request and reflected back in the response so callers can correlate
client-side logs with server-side logs.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import uuid4

from core.observability import bind_request_context, clear_request_context
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Bind a per-request correlation id into the structlog context."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(_HEADER) or str(uuid4())
        request.state.request_id = request_id

        bind_request_context(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            clear_request_context()

        response.headers[_HEADER] = request_id
        return response
