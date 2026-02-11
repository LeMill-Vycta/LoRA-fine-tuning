from __future__ import annotations

from time import perf_counter

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_COUNT = Counter(
    "lora_studio_requests_total",
    "Total HTTP requests",
    labelnames=("endpoint", "method", "status"),
)
REQUEST_LATENCY = Histogram(
    "lora_studio_request_latency_seconds",
    "HTTP request latency in seconds",
    labelnames=("endpoint", "method"),
)
RUN_TRANSITIONS = Counter(
    "lora_studio_run_transitions_total",
    "Training run state transitions",
    labelnames=("state",),
)
RUN_FAILURES = Counter(
    "lora_studio_run_failures_total",
    "Training run failures",
)
INGESTED_DOCUMENTS = Counter(
    "lora_studio_documents_ingested_total",
    "Documents ingested",
    labelnames=("status",),
)
INFERENCE_REQUESTS = Counter(
    "lora_studio_inference_total",
    "Inference requests",
    labelnames=("refused",),
)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        started = perf_counter()
        endpoint = request.url.path
        status = "500"
        try:
            response = await call_next(request)
            status = str(response.status_code)
            return response
        finally:
            REQUEST_COUNT.labels(endpoint=endpoint, method=request.method, status=status).inc()
            REQUEST_LATENCY.labels(endpoint=endpoint, method=request.method).observe(
                perf_counter() - started
            )


def render_metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
