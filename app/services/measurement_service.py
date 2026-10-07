import logging
import math
from uuid import UUID

from pyproj import CRS, Transformer
from pyproj.exceptions import ProjError
from shapely.errors import GEOSException
from shapely.geometry import mapping
from shapely.ops import transform
from shapely.validation import explain_validity

from app.core.exceptions import CRSProcessingError
from app.models.file import Dataset, SourceFeature
from app.schemas.file import FeatureMeasurement, Measurement, MeasurementsResponse
from app.services.crs_service import (
    crosses_antimeridian,
    geographic_geometry,
    select_measurement_crs,
)

logger = logging.getLogger(__name__)
AREA_TYPES = {"Polygon", "MultiPolygon"}
LENGTH_TYPES = {"LineString", "MultiLineString"}


def measure_feature(
    feature: SourceFeature,
    index: int,
    transformer: Transformer | None,
    crs_error: str | None,
    source_crs: CRS,
) -> FeatureMeasurement:
    geometry = feature.geometry
    result = FeatureMeasurement(
        feature_id=index,
        source_feature_id=feature.source_id,
        layer=feature.layer,
        geometry_type=geometry.geom_type if geometry is not None else None,
        geometry=mapping(geometry) if geometry is not None and not geometry.is_empty else None,
        properties=feature.properties,
    )
    if geometry is None or geometry.is_empty:
        result.measurement_error = "Geometry is null or empty."
    elif not geometry.is_valid:
        result.measurement_error = "Invalid geometry: " + explain_validity(geometry)
    elif geometry.geom_type in {"Point", "MultiPoint"}:
        pass
    elif geometry.geom_type not in AREA_TYPES | LENGTH_TYPES:
        result.measurement_error = (
            f"Geometry type {geometry.geom_type} is not supported for measurement."
        )
    elif crs_error or transformer is None:
        result.measurement_error = crs_error or "No measurement CRS could be selected."
    else:
        try:
            if transformer.source_crs != transformer.target_crs and crosses_antimeridian(
                geographic_geometry(source_crs, geometry)
            ):
                result.measurement_error = (
                    "Dateline-crossing lines and polygons require specialized handling."
                )
                return result
            projected = transform(
                lambda x, y, z=None: transformer.transform(x, y, z, errcheck=True), geometry
            )
            area = geometry.geom_type in AREA_TYPES
            value = float(projected.area if area else projected.length)
            if not math.isfinite(value) or not projected.is_valid:
                raise ValueError("Nonfinite or invalid projected geometry")
            result.measurement = Measurement(
                type="area" if area else "length",
                value=value,
                unit="square_meters" if area else "meters",
            )
        except (CRSProcessingError, ProjError, GEOSException, ValueError) as exc:
            logger.warning("Feature %s could not be measured: %s", index, type(exc).__name__)
            result.measurement_error = "Geometry could not be transformed or measured safely."
    return result


def measure_dataset(dataset: Dataset, file_id: UUID) -> MeasurementsResponse:
    logger.info("Measurement processing file_id=%s features=%s", file_id, len(dataset.features))
    crs_error = None
    target = None
    transformer = None
    try:
        target = select_measurement_crs(
            dataset.crs,
            [
                feature.geometry
                for feature in dataset.features
                if feature.geometry is not None
                and feature.geometry.is_valid
                and not feature.geometry.is_empty
            ],
        )
        if target is not None:
            transformer = Transformer.from_crs(dataset.crs, target, always_xy=True)
    except (CRSProcessingError, ProjError) as exc:
        logger.warning("CRS selection failed file_id=%s: %s", file_id, exc)
        crs_error = (
            str(exc) if isinstance(exc, CRSProcessingError) else "CRS transformation unavailable."
        )
        target = None
    return MeasurementsResponse(
        file_id=file_id,
        crs=dataset.crs.to_string(),
        measurement_crs=target.to_string() if target else None,
        features=[
            measure_feature(feature, index, transformer, crs_error, dataset.crs)
            for index, feature in enumerate(dataset.features)
        ],
    )
