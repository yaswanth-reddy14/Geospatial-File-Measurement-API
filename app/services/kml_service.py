import math
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, ParseError

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from pyproj import CRS
from shapely.errors import GEOSException
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)
from shapely.geometry.base import BaseGeometry

from app.core.config import Settings
from app.core.exceptions import InvalidGeospatialFileError
from app.models.file import Dataset, SourceFeature

NS = "{http://www.opengis.net/kml/2.2}"
GEOMETRY_TAGS = {NS + name for name in ("Point", "LineString", "Polygon", "MultiGeometry")}


def coordinates(node: Element | None) -> list[tuple[float, ...]]:
    if node is None:
        raise InvalidGeospatialFileError("KML geometry is missing its coordinates element.")
    result = []
    for token in (node.text or "").split():
        values = tuple(float(value) for value in token.split(","))
        if len(values) not in (2, 3) or not all(math.isfinite(value) for value in values):
            raise InvalidGeospatialFileError("KML coordinates must be finite lon,lat[,alt] values.")
        if not (-180 <= values[0] <= 180 and -90 <= values[1] <= 90):
            raise InvalidGeospatialFileError(
                "KML longitude or latitude is outside its valid range."
            )
        result.append(values)
    if result and len({len(value) for value in result}) != 1:
        raise InvalidGeospatialFileError("KML geometry has inconsistent coordinate dimensions.")
    return result


def ring(node: Element | None) -> list[tuple[float, ...]]:
    if node is None:
        raise InvalidGeospatialFileError("KML polygon is missing its boundary ring.")
    values = coordinates(node.find(NS + "coordinates"))
    if values and (len(values) < 4 or values[0] != values[-1]):
        raise InvalidGeospatialFileError(
            "KML polygon rings must be closed with at least four positions."
        )
    return values


def parse_geometry(node: Element) -> BaseGeometry:
    name = node.tag.removeprefix(NS)
    if name in ("Point", "LineString"):
        values = coordinates(node.find(NS + "coordinates"))
        if name == "Point":
            if len(values) > 1:
                raise InvalidGeospatialFileError("A KML Point must have a single position.")
            return Point(values[0]) if values else Point()
        return LineString(values)
    if name == "Polygon":
        shell = ring(node.find(f"{NS}outerBoundaryIs/{NS}LinearRing"))
        holes = [
            ring(item.find(NS + "LinearRing")) for item in node.findall(NS + "innerBoundaryIs")
        ]
        return Polygon(shell, holes)
    if any(child.tag == NS + "LinearRing" for child in node):
        raise InvalidGeospatialFileError("Standalone KML LinearRing is not supported.")
    children = [parse_geometry(child) for child in node if child.tag in GEOMETRY_TAGS]
    # Flatten nested compatible multi-geometries without discarding empty parts.
    children = [
        part
        for child in children
        for part in (child.geoms if hasattr(child, "geoms") and not child.is_empty else [child])
    ]
    if children and not any(child.is_empty for child in children):
        if all(isinstance(child, Polygon) for child in children):
            return MultiPolygon(children)
        if all(isinstance(child, LineString) for child in children):
            return MultiLineString(children)
        if all(isinstance(child, Point) for child in children):
            return MultiPoint(children)
    return GeometryCollection(children)


def read_kml(path: Path, settings: Settings) -> Dataset:
    """Read standard KML 2.2 placemarks without resolving links or XML entities."""
    try:
        root = ElementTree.parse(path, forbid_dtd=True, forbid_entities=True).getroot()
        if root.tag != NS + "kml":
            raise InvalidGeospatialFileError(
                "Expected a KML 2.2 document with the standard namespace."
            )
        if any(
            node.tag in {NS + "NetworkLink", NS + "Model", NS + "LinearRing"}
            for node in root
            if node.tag != NS + "Document"
        ):
            raise InvalidGeospatialFileError("Unsupported top-level KML content.")
        # Reject unsupported geometry rather than silently losing placemarks.
        forbidden = {"Track", "MultiTrack", "Model", "NetworkLink"}
        geometry_names = {tag.removeprefix(NS) for tag in GEOMETRY_TAGS} | {"LinearRing"}
        if any(
            node.tag.rsplit("}", 1)[-1] in geometry_names and not node.tag.startswith(NS)
            for node in root.iter()
        ):
            raise InvalidGeospatialFileError("KML geometry has an invalid namespace.")
        if any(node.tag.rsplit("}", 1)[-1] in forbidden for node in root.iter()):
            raise InvalidGeospatialFileError(
                "KML tracks, models, and network links are not supported."
            )
        placemarks = list(root.iter(NS + "Placemark"))
        if not placemarks or len(placemarks) > settings.max_features:
            raise InvalidGeospatialFileError("KML has no placemarks or exceeds the feature limit.")
        features = []
        for placemark in placemarks:
            nodes = [child for child in placemark if child.tag in GEOMETRY_TAGS]
            if len(nodes) > 1:
                raise InvalidGeospatialFileError(
                    "Use MultiGeometry for multiple placemark geometries."
                )
            if any(child.tag == NS + "LinearRing" for child in placemark):
                raise InvalidGeospatialFileError("Standalone KML LinearRing is not supported.")
            properties: dict[str, Any] = {}
            for name in ("name", "description", "address"):
                node = placemark.find(NS + name)
                if node is not None:
                    properties[name] = node.text
            # Keep the existing flat aliases for noncolliding custom fields, but
            # retain every entry (including duplicates and schema identities) in
            # a separate ordered record. Standard metadata always keeps its key.
            entries = []
            for item in placemark.findall(f"{NS}ExtendedData/{NS}Data"):
                key = item.get("name")
                if key:
                    value = item.findtext(NS + "value")
                    entries.append(
                        {
                            "kind": "Data",
                            "name": key,
                            "value": value,
                            "display_name": item.findtext(NS + "displayName"),
                        }
                    )
                    if key != "extended_data":
                        properties.setdefault(key, value)
            for schema in placemark.findall(f"{NS}ExtendedData/{NS}SchemaData"):
                for item in schema.findall(NS + "SimpleData"):
                    key = item.get("name")
                    if key:
                        entries.append(
                            {
                                "kind": "SimpleData",
                                "schema_url": schema.get("schemaUrl"),
                                "name": key,
                                "value": item.text,
                            }
                        )
                        if key != "extended_data":
                            properties.setdefault(key, item.text)
            if entries:
                properties["extended_data"] = entries
            features.append(
                SourceFeature(
                    geometry=parse_geometry(nodes[0]) if nodes else None,
                    properties=properties,
                    source_id=placemark.get("id"),
                    layer="KML",
                )
            )
        return Dataset(CRS.from_epsg(4326), features)
    except (
        ParseError,
        DefusedXmlException,
        ValueError,
        LookupError,
        GEOSException,
        RecursionError,
    ) as exc:
        raise InvalidGeospatialFileError("Malformed KML document or geometry.") from exc
