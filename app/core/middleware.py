from __future__ import annotations

import logging
import uuid
from time import perf_counter

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        started = perf_counter()

        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id

        logger.info(
            "http_request_completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "latency_ms": int((perf_counter() - started) * 1000),
            },
        )
        return response
