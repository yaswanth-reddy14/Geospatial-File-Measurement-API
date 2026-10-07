from dataclasses import dataclass
from typing import Any

from pyproj import CRS
from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class SourceFeature:
    geometry: BaseGeometry | None
    properties: dict[str, Any]
    source_id: str | None = None
    layer: str | None = None


@dataclass(frozen=True)
class Dataset:
    crs: CRS
    features: list[SourceFeature]
