import math

import numpy as np
from pyproj import CRS, Transformer
from pyproj.exceptions import ProjError
from shapely import get_coordinates
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

from app.core.exceptions import CRSProcessingError


def utm_crs(longitude: float, latitude: float) -> CRS:
    """Select WGS84 UTM (including Norway/Svalbard exceptions), or polar UPS."""
    if not (math.isfinite(longitude) and math.isfinite(latitude)):
        raise CRSProcessingError("Cannot select a CRS from nonfinite coordinates.")
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        raise CRSProcessingError("Location is outside the valid longitude/latitude range.")
    if latitude > 84 or latitude < -80:
        return CRS.from_epsg(32661 if latitude >= 0 else 32761)
    zone = min(60, max(1, math.floor((longitude + 180) / 6) + 1))
    if 56 <= latitude < 64 and 3 <= longitude < 12:
        zone = 32
    elif 72 <= latitude <= 84 and 0 <= longitude < 42:
        zone = 31 if longitude < 9 else 33 if longitude < 21 else 35 if longitude < 33 else 37
    return CRS.from_epsg((32600 if latitude >= 0 else 32700) + zone)


def is_metric_projected(crs: CRS) -> bool:
    """Trust a supplied metre-based projection, except distorted Web Mercator."""
    return (
        crs.is_projected
        and crs.to_epsg() not in {3857, 3395}
        and len(crs.axis_info) >= 2
        and all(math.isclose(axis.unit_conversion_factor, 1.0) for axis in crs.axis_info[:2])
    )


def wgs84_coordinates(source: CRS, coords: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Normalize angular units and reject invalid values before PROJ can wrap them."""
    if source.is_geographic:
        axes = source.axis_info[:2]
        longitude_axis = next((a for a in axes if a.direction in {"east", "west"}), axes[0])
        latitude_axis = next((a for a in axes if a.direction in {"north", "south"}), axes[1])
        degrees = (
            coords
            * np.array(
                [
                    longitude_axis.unit_conversion_factor,
                    latitude_axis.unit_conversion_factor,
                ]
            )
            * (180 / math.pi)
        )
        if np.any(np.abs(degrees[:, 0]) > 180 + 1e-9) or np.any(np.abs(degrees[:, 1]) > 90 + 1e-9):
            raise CRSProcessingError("Geographic coordinates are outside valid ranges.")
    try:
        lon, lat = Transformer.from_crs(source, 4326, always_xy=True).transform(
            coords[:, 0].tolist(), coords[:, 1].tolist(), errcheck=True
        )
    except ProjError as exc:
        raise CRSProcessingError("Unable to transform source coordinates to WGS84.") from exc
    lon, lat = np.asarray(lon), np.asarray(lat)
    if (
        not np.isfinite(lon).all()
        or not np.isfinite(lat).all()
        or np.any(np.abs(lon) > 180 + 1e-9)
        or np.any(np.abs(lat) > 90 + 1e-9)
    ):
        raise CRSProcessingError("Dataset cannot be located in valid WGS84 coordinates.")
    return lon, lat


def geographic_geometry(source: CRS, geometry: BaseGeometry) -> BaseGeometry:
    """Normalize geometry before longitude-jump checks, including grad-based CRS."""
    transformer = Transformer.from_crs(source, 4326, always_xy=True)
    return transform(lambda x, y, z=None: transformer.transform(x, y, z, errcheck=True), geometry)


def select_measurement_crs(source: CRS, geometries: list[BaseGeometry]) -> CRS | None:
    if is_metric_projected(source):
        return source
    if not (source.is_geographic or source.is_projected):
        raise CRSProcessingError("Only geographic and projected source CRS are supported.")
    arrays = [get_coordinates(geometry) for geometry in geometries if not geometry.is_empty]
    if not arrays:
        return None
    coords = np.concatenate(arrays)
    lon, lat = wgs84_coordinates(source, coords)
    if source.is_projected:
        # Endpoints alone do not describe straight segments in the source CRS.
        # Conservatively inspect the entire source envelope, including interiors.
        # The bounded 33x33 grid avoids allocating per-vertex densification arrays.
        xmin, ymin = np.min(coords, axis=0)
        xmax, ymax = np.max(coords, axis=0)
        x, y = np.meshgrid(np.linspace(xmin, xmax, 33), np.linspace(ymin, ymax, 33))
        envelope_lon, envelope_lat = wgs84_coordinates(
            source, np.column_stack((x.ravel(), y.ravel()))
        )
        if (
            np.ptp(envelope_lon) > 6
            or np.ptp(envelope_lat) > 8
            or np.any(np.abs(np.diff(envelope_lon.reshape(33, 33), axis=1)) > 180)
            or np.any(np.abs(np.diff(envelope_lon.reshape(33, 33), axis=0)) > 180)
        ):
            raise CRSProcessingError(
                "Geometry extent is too broad or crosses an unsafe projection boundary "
                "for reliable planar measurement; split it into regional datasets."
            )
        lon = np.concatenate((lon, envelope_lon))
        lat = np.concatenate((lat, envelope_lat))
    # Find the smallest longitude arc: points close across the dateline stay close.
    sorted_lon = np.sort(np.mod(lon, 360))
    gaps = np.diff(np.concatenate([sorted_lon, [sorted_lon[0] + 360]]))
    gap_index = int(np.argmax(gaps))
    span = 360 - float(gaps[gap_index])
    start = float(sorted_lon[(gap_index + 1) % len(sorted_lon)])
    midpoint = (start + span / 2) % 360
    longitude = midpoint if midpoint <= 180 else midpoint - 360
    latitude = float((np.min(lat) + np.max(lat)) / 2)
    if span > 6 or np.ptp(lat) > 8:
        raise CRSProcessingError(
            "Dataset extent exceeds the local projection policy (6 degrees longitude, "
            "8 degrees latitude); split it into regional datasets."
        )
    return utm_crs(longitude, latitude)


def crosses_antimeridian(geometry: BaseGeometry) -> bool:
    """Detect ring/line jumps without confusing disconnected multi-geometry parts."""
    if geometry.geom_type == "Polygon":
        return any(
            np.any(np.abs(np.diff(np.asarray(ring.coords)[:, 0])) > 180)
            for ring in [geometry.exterior, *geometry.interiors]
        )
    if geometry.geom_type in {"LineString", "LinearRing"}:
        return bool(np.any(np.abs(np.diff(np.asarray(geometry.coords)[:, 0])) > 180))
    if hasattr(geometry, "geoms"):
        return any(crosses_antimeridian(part) for part in geometry.geoms)
    return False
