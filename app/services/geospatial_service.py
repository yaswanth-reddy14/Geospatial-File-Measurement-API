import math
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyogrio
from pyogrio.errors import DataLayerError, DataSourceError, FeatureError, GeometryError
from pyogrio.raw import read as read_raw
from pyproj import CRS
from pyproj.exceptions import CRSError
from shapely import from_wkb, get_coordinates, get_parts
from shapely.geometry.base import BaseGeometry

from app.core.config import Settings
from app.core.exceptions import CRSProcessingError, InvalidGeospatialFileError
from app.models.file import Dataset, SourceFeature
from app.services.archive_service import extract_shapefile
from app.services.crs_service import wgs84_coordinates
from app.services.kml_service import read_kml


def json_value(value: Any) -> Any:
    """Normalize DBF scalars and nested properties without allowing NaN in JSON."""
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [json_value(item) for item in value]
    if isinstance(value, np.generic):
        return json_value(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if pd.isna(value):
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def read_shapefile(path: Path, settings: Settings) -> Dataset:
    try:
        info = pyogrio.read_info(path, force_feature_count=True)
        if info["driver"] != "ESRI Shapefile":
            raise InvalidGeospatialFileError("Archive does not contain a real Shapefile.")
        if info["features"] <= 0 or info["features"] > settings.max_features:
            raise InvalidGeospatialFileError("Shapefile is empty or exceeds the feature limit.")
        # Read geometry and DBF arrays separately: a GeoDataFrame would overwrite
        # a legitimate attribute called "geometry" before we could preserve it.
        metadata, fids, wkb, fields = read_raw(path, return_fids=True)
        if metadata["crs"] is None:
            raise CRSProcessingError(
                "Shapefile CRS is missing or invalid; provide a valid .prj file."
            )
        features = [
            SourceFeature(
                geometry=geometry,
                properties={
                    str(key): json_value(values[position])
                    for key, values in zip(metadata["fields"], fields, strict=True)
                },
                source_id=str(index),
                layer="Shapefile",
            )
            for position, (index, geometry) in enumerate(zip(fids, from_wkb(wkb), strict=True))
        ]
        return Dataset(CRS.from_user_input(metadata["crs"]), features)
    except (DataSourceError, DataLayerError, FeatureError, GeometryError, ValueError) as exc:
        raise InvalidGeospatialFileError("Invalid or corrupted Shapefile dataset.") from exc
    except CRSError as exc:
        raise CRSProcessingError("Unable to interpret the source CRS.") from exc


def read_dataset(path: Path, file_type: str, settings: Settings) -> Dataset:
    if file_type == "kml":
        dataset = read_kml(path, settings)
    else:
        with tempfile.TemporaryDirectory(prefix="geospatial-") as directory:
            shp = extract_shapefile(path, Path(directory), settings)
            dataset = read_shapefile(shp, settings)
    count = 0
    for feature in dataset.features:
        coords = get_coordinates(feature.geometry, include_z=False)
        count += len(coords)
        if count > settings.max_coordinates:
            raise InvalidGeospatialFileError("Dataset exceeds the coordinate limit.")
        if not np.isfinite(coords).all():
            raise InvalidGeospatialFileError("Geometry contains nonfinite coordinates.")
        if dataset.crs.is_geographic and len(coords):
            try:
                wgs84_coordinates(dataset.crs, coords)
            except CRSProcessingError as exc:
                raise InvalidGeospatialFileError(str(exc)) from exc
        validate_altitudes(feature.geometry)
    return dataset


def validate_altitudes(geometry: BaseGeometry | None) -> None:
    """Absent Z in a 2D collection member is valid, unlike nonfinite explicit altitude."""
    if geometry is None or geometry.is_empty:
        return
    if hasattr(geometry, "geoms"):
        for part in get_parts(geometry):
            validate_altitudes(part)
    elif geometry.has_z and not np.isfinite(get_coordinates(geometry, include_z=True)).all():
        raise InvalidGeospatialFileError("Geometry contains nonfinite altitude values.")
