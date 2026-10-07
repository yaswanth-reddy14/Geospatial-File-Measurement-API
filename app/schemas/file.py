from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FileStatus(StrEnum):
    COMPLETED = "COMPLETED"


class FileInfoResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "b2b9cbbc-92ca-4a83-9f00-1733ce7b31d4",
                "filename": "survey.kml",
                "file_type": "kml",
                "feature_count": 3,
                "crs": "EPSG:4326",
                "status": "COMPLETED",
                "geometry_types": ["LineString", "Point", "Polygon"],
                "created_at": "2026-01-01T12:00:00Z",
                "processing_time_ms": 25.4,
            }
        }
    )

    id: UUID
    filename: str
    file_type: Literal["kml", "zip"]
    feature_count: int = Field(ge=0)
    crs: str
    status: FileStatus = FileStatus.COMPLETED
    geometry_types: list[str]
    created_at: datetime
    processing_time_ms: float = Field(ge=0)


class FileUploadResponse(FileInfoResponse):
    pass


class Measurement(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    type: Literal["area", "length"]
    value: float = Field(ge=0)
    unit: Literal["square_meters", "meters"]


class FeatureMeasurement(BaseModel):
    feature_id: int
    source_feature_id: str | None = None
    layer: str | None = None
    geometry_type: str | None
    geometry: dict[str, Any] | None
    properties: dict[str, Any]
    measurement: Measurement | None = None
    measurement_error: str | None = None


class MeasurementsResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "file_id": "b2b9cbbc-92ca-4a83-9f00-1733ce7b31d4",
                "crs": "EPSG:4326",
                "measurement_crs": "EPSG:32644",
                "features": [
                    {
                        "feature_id": 0,
                        "source_feature_id": "station-1",
                        "layer": "survey",
                        "geometry_type": "Point",
                        "geometry": {"type": "Point", "coordinates": [80, 13]},
                        "properties": {"name": "Station"},
                        "measurement": None,
                        "measurement_error": None,
                    }
                ],
            }
        }
    )
    file_id: UUID
    crs: str
    measurement_crs: str | None
    features: list[FeatureMeasurement]


class ErrorResponse(BaseModel):
    detail: str
