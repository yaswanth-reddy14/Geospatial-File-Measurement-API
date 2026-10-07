from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from app.schemas.file import (
    ErrorResponse,
    FileInfoResponse,
    FileUploadResponse,
    MeasurementsResponse,
)
from app.services.file_service import FileService

router = APIRouter(prefix="/api/files", tags=["Files"])
ERROR_RESPONSES = {
    400: {"model": ErrorResponse, "description": "Invalid or unsupported geospatial input"},
    413: {"model": ErrorResponse, "description": "Upload or request body exceeds configured size"},
    422: {"description": "Invalid request parameters or unusable source CRS"},
    500: {"model": ErrorResponse, "description": "Unexpected processing or storage failure"},
}


def get_file_service(request: Request) -> FileService:
    return request.app.state.file_service


Service = Annotated[FileService, Depends(get_file_service)]


@router.post(
    "/",
    response_model=FileUploadResponse,
    status_code=201,
    summary="Upload and measure a geospatial file",
    responses=ERROR_RESPONSES,
    description="Accept a KML 2.2 file or ZIP containing one Shapefile with .shp, .shx, .dbf "
    "and .prj components. Processes synchronously and persists completed results. "
    "Individual geometry failures are reported in the measurements response.",
)
async def upload_file(
    response: Response,
    service: Service,
    file: Annotated[UploadFile, File(description="A .kml file or a .zip Shapefile archive")],
) -> FileUploadResponse:
    try:
        result = await run_in_threadpool(
            service.process_upload, file.file, file.filename, file.content_type
        )
        response.headers["Location"] = f"/api/files/{result.id}/"
        return result
    finally:
        await file.close()


@router.get(
    "/{file_id}/",
    response_model=FileInfoResponse,
    summary="Retrieve uploaded file metadata",
    description="Return the persisted source CRS, feature count, and completion metadata.",
    responses={404: {"model": ErrorResponse, "description": "File does not exist"}},
)
def file_info(file_id: UUID, service: Service) -> FileInfoResponse:
    return service.repository.get(file_id)


@router.get(
    "/{file_id}/measurements/",
    response_model=MeasurementsResponse,
    summary="Retrieve measurements and original feature geometries",
    description="Return every feature in source CRS coordinates. Measurements are 2D metres "
    "or square metres in measurement_crs. Points have no measurement; invalid, "
    "empty, unsupported, or unsafe geometries have a per-feature error.",
    responses={
        404: {"model": ErrorResponse, "description": "File does not exist"},
        500: {"model": ErrorResponse, "description": "Stored results are unavailable"},
    },
)
def file_measurements(file_id: UUID, service: Service) -> MeasurementsResponse:
    return service.get_measurements(file_id)
