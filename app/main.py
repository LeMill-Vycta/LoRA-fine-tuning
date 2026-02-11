from __future__ import annotations

import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import router as api_router
from app.core.config import get_settings
from app.core.db import init_db
from app.core.logging import configure_logging
from app.core.metrics import MetricsMiddleware
from app.core.middleware import RequestContextMiddleware
from app.services.worker import BackgroundWorker
from app.web.router import router as web_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    init_db()

    worker = BackgroundWorker()
    app.state.worker = worker
    worker.start()

    logger.info(
        "application_started",
        extra={
            "app_name": settings.app_name,
            "version": settings.app_version,
            "environment": settings.environment,
            "metrics_enabled": settings.enable_metrics,
        },
    )
    yield

    worker.stop()
    logger.info("application_stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Production-grade LoRA fine-tuning studio for niche expertise.",
        lifespan=lifespan,
    )

    app.add_middleware(RequestContextMiddleware)
    if settings.enable_metrics:
        app.add_middleware(MetricsMiddleware)

    app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
    app.include_router(web_router)
    app.include_router(api_router)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", None)
        logger.exception(
            "unhandled_exception",
            extra={
                "request_id": request_id,
                "path": request.url.path,
                "method": request.method,
            },
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal server error",
                "request_id": request_id,
            },
        )

    return app


app = create_app()
