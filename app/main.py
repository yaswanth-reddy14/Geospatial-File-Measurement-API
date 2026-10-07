import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.routes.files import router
from app.core.config import Settings
from app.core.exceptions import ApplicationError
from app.core.logging import configure_logging
from app.core.middleware import UploadBodyLimitMiddleware
from app.repositories.file_repository import FileRepository
from app.services.file_service import FileService

logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: str = "ok"


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configure_logging(config.log_level)
        config.upload_dir.mkdir(parents=True, exist_ok=True)
        config.processed_dir.mkdir(parents=True, exist_ok=True)
        repository = FileRepository(config.database_path)
        repository.initialize()
        application.state.file_service = FileService(config, repository)
        yield

    application = FastAPI(
        title="Geospatial File Measurement API",
        version="1.0.0",
        description="Upload KML and zipped Shapefiles for secure, CRS-aware feature measurements.",
        lifespan=lifespan,
    )
    application.add_middleware(
        UploadBodyLimitMiddleware, max_bytes=config.max_upload_bytes + 1024 * 1024
    )
    application.include_router(router)

    @application.exception_handler(ApplicationError)
    async def application_error_handler(request: Request, exc: ApplicationError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @application.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled request failure method=%s", request.method, exc_info=exc)
        return JSONResponse(
            status_code=500, content={"detail": "An internal processing error occurred."}
        )

    @application.get(
        "/health", response_model=HealthResponse, tags=["Health"], summary="Service liveness check"
    )
    def health() -> HealthResponse:
        return HealthResponse()

    @application.get("/", tags=["Health"], summary="API entry point")
    def root() -> dict[str, str]:
        return {"name": "Geospatial File Measurement API", "version": "1.0.0", "docs": "/docs"}

    return application


app = create_app()
