import io
import zipfile
from pathlib import Path

import geopandas as gpd
from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import transform


def metric_polygon() -> Polygon:
    return Polygon(
        [
            (500000, 1500000),
            (500100, 1500000),
            (500100, 1500100),
            (500000, 1500100),
            (500000, 1500000),
        ]
    )


def to_wgs84(geometry):
    return transform(Transformer.from_crs(32644, 4326, always_xy=True).transform, geometry)


def coordinate_text(coords) -> str:
    return " ".join(",".join(str(value) for value in coord) for coord in coords)


def kml_document(placemarks: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>' + placemarks + "</Document></kml>"
    ).encode()


def mixed_kml() -> bytes:
    polygon = to_wgs84(metric_polygon())
    line = to_wgs84(LineString([(500000, 1500000), (500100, 1500000)]))
    point = to_wgs84(Point(500000, 1500000))
    return kml_document(
        '<Placemark id="parcel"><name>Parcel A</name>'
        '<ExtendedData><Data name="owner"><value>Alice</value></Data></ExtendedData>'
        "<Polygon><outerBoundaryIs><LinearRing><coordinates>"
        + coordinate_text(polygon.exterior.coords)
        + "</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>"
        '<Placemark id="road"><name>Road</name><LineString><coordinates>'
        + coordinate_text(line.coords)
        + "</coordinates></LineString></Placemark>"
        '<Placemark id="station"><name>Station</name><Point><coordinates>'
        + coordinate_text(point.coords)
        + "</coordinates></Point></Placemark>"
    )


def shapefile_zip(directory: Path, geometry=None, crs="EPSG:32644") -> bytes:
    directory.mkdir(parents=True, exist_ok=True)
    frame = gpd.GeoDataFrame(
        {"name": ["Parcel A"], "score": [7]},
        geometry=[geometry if geometry is not None else metric_polygon()],
        crs=crs,
    )
    frame.to_file(directory / "parcel.shp", engine="pyogrio", driver="ESRI Shapefile")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.iterdir()):
            archive.write(path, "nested/" + path.name)
        archive.writestr("README.txt", "Extra non-geospatial files are permitted.")
    return output.getvalue()


def zip_entries(entries: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return output.getvalue()
