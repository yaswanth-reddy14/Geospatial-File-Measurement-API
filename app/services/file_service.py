import logging
import re
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

from app.core.config import Settings
from app.core.exceptions import (
    ApplicationError,
    InvalidGeospatialFileError,
    UnsupportedFileTypeError,
    UploadTooLargeError,
)
from app.repositories.file_repository import FileRepository
from app.schemas.file import FileUploadResponse, MeasurementsResponse
from app.services.geospatial_service import read_dataset
from app.services.measurement_service import measure_dataset

logger = logging.getLogger(__name__)
MIME_TYPES = {
    "kml": {
        "application/vnd.google-earth.kml+xml",
        "application/xml",
        "text/xml",
        "text/plain",
        "application/octet-stream",
    },
    "zip": {"application/zip", "application/x-zip-compressed", "application/octet-stream"},
}


def validate_filename(filename: str | None, content_type: str | None) -> tuple[str, str]:
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[^\w.() -]", "_", name).strip(" .")
    if not name or len(name) > 200:
        raise InvalidGeospatialFileError("Provide a valid filename of at most 200 characters.")
    extension = Path(name).suffix.lower().removeprefix(".")
    if extension not in MIME_TYPES:
        raise UnsupportedFileTypeError(
            "Unsupported file type. Only .kml and .zip Shapefile archives are supported."
        )
    mime = (content_type or "application/octet-stream").split(";", 1)[0].strip().lower()
    if mime not in MIME_TYPES[extension]:
        raise InvalidGeospatialFileError("Content type is incompatible with the file extension.")
    return name, extension


class FileService:
    def __init__(self, settings: Settings, repository: FileRepository) -> None:
        self.settings = settings
        self.repository = repository

    def process_upload(
        self,
        source: BinaryIO,
        filename: str | None,
        content_type: str | None,
    ) -> FileUploadResponse:
        started = time.perf_counter()
        uploaded_at = datetime.now(UTC)
        file_id = uuid4()
        raw_path: Path | None = None
        processed_path: Path | None = None
        try:
            name, file_type = validate_filename(filename, content_type)
            logger.info("Upload started file_id=%s type=%s", file_id, file_type)
            with tempfile.TemporaryDirectory(
                prefix="upload-", dir=self.settings.upload_dir
            ) as temp:
                temporary_raw = Path(temp) / ("input." + file_type)
                size = 0
                with temporary_raw.open("wb") as output:
                    while chunk := source.read(64 * 1024):
                        size += len(chunk)
                        if size > self.settings.max_upload_bytes:
                            raise UploadTooLargeError("Uploaded file exceeds the size limit.")
                        output.write(chunk)
                if size == 0:
                    raise InvalidGeospatialFileError("Uploaded file is empty.")
                logger.info("Processing started file_id=%s bytes=%s", file_id, size)
                dataset = read_dataset(temporary_raw, file_type, self.settings)
                measurements = measure_dataset(dataset, file_id)
                metadata = FileUploadResponse(
                    id=file_id,
                    filename=name,
                    file_type=file_type,
                    feature_count=len(dataset.features),
                    crs=dataset.crs.to_string(),
                    geometry_types=sorted(
                        {
                            feature.geometry.geom_type
                            for feature in dataset.features
                            if feature.geometry is not None
                        }
                    ),
                    created_at=uploaded_at,
                    processing_time_ms=round((time.perf_counter() - started) * 1000, 3),
                )
                raw_path = self.settings.upload_dir / f"{file_id}.{file_type}"
                processed_path = self.settings.processed_dir / f"{file_id}.json"
                # Write privately on the same filesystem, then atomically rename each artifact.
                with tempfile.TemporaryDirectory(dir=self.settings.processed_dir) as result_temp:
                    temporary_result = Path(result_temp) / "result.json"
                    temporary_result.write_text(measurements.model_dump_json(), encoding="utf-8")
                    temporary_result.replace(processed_path)
                temporary_raw.replace(raw_path)
            # Publish metadata only after complete artifacts and temporary cleanup succeed.
            self.repository.save(metadata, raw_path.name)
            logger.info(
                "Processing completed file_id=%s features=%s", file_id, metadata.feature_count
            )
            logger.info("Upload completed file_id=%s", file_id)
            return metadata
        except Exception as exc:
            # Compensating cleanup applies to both validation and unexpected storage failures.
            for artifact in (raw_path, processed_path):
                if artifact is not None:
                    artifact.unlink(missing_ok=True)
            if isinstance(exc, ApplicationError):
                logger.warning("Validation failed file_id=%s reason=%s", file_id, exc)
            else:
                logger.exception("Processing failure file_id=%s", file_id)
            raise

    def get_measurements(self, file_id: UUID) -> MeasurementsResponse:
        self.repository.get(file_id)
        # The UUID is parsed by FastAPI; user filenames never become storage paths.
        path = self.settings.processed_dir / f"{file_id}.json"
        return MeasurementsResponse.model_validate_json(path.read_text(encoding="utf-8"))
