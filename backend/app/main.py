from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    admin,
    appointments,
    chat,
    doctors,
    inbound,
    labs,
    me,
    patients,
    records,
    reports,
)
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import add_request_logging, configure_logging
from app.core.rate_limit import register_rate_limiting
from app.db.session import dispose_engine, get_sessionmaker
from app.services.ingestion.worker import IngestionWorker


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    # One ingestion worker per API process (uvicorn runs without --reload, so this runs once).
    worker = IngestionWorker(get_sessionmaker(), settings.ingestion_poll_seconds)
    if settings.ingestion_worker_enabled:
        worker.start()
    try:
        yield
    finally:
        await worker.stop()
        await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    is_dev = settings.env == "dev"
    app = FastAPI(
        title="MediFlow API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs" if is_dev else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if is_dev else None,
    )
    register_error_handlers(app)
    register_rate_limiting(app)
    add_request_logging(app)
    # Added last so it is the outermost middleware and error responses carry CORS headers.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key"],
        expose_headers=["X-Request-ID"],
    )

    @app.get("/api/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    for module in (
        me,
        appointments,
        patients,
        doctors,
        admin,
        inbound,
        records,
        reports,
        chat,
        labs,
    ):
        app.include_router(module.router, prefix="/api")
    return app


app = create_app()
