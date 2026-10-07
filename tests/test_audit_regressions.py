"""Identical upload assertions run in-process or against a real HTTP server."""

import io
import math
import zipfile

import geopandas as gpd
import pyogrio
import pytest
from pyproj import CRS, Geod, Transformer
from shapely.affinity import translate
from shapely.geometry import LineString, MultiPolygon, Point
from shapely.ops import transform

from tests.helpers import kml_document, metric_polygon, shapefile_zip, to_wgs84


def upload_results(client, filename, contents):
    response = client.post("/api/files/", files={"file": (filename, contents)})
    assert response.status_code == 201, response.text
    location = response.headers["location"]
    assert client.get(location).json() == response.json()
    measured = client.get(location + "measurements/")
    assert measured.status_code == 200, measured.text
    return measured.json()


def test_shapefile_geometry_attribute_survives(regression_client, tmp_path):
    directory = tmp_path / "collision"
    directory.mkdir()
    source = directory / "collision.shp"
    frame = gpd.GeoDataFrame(
        {"geometry": ["business attribute"], "value": [42], "_shape": [Point(500000, 1500000)]},
        geometry="_shape",
        crs=32644,
    )
    frame.to_file(source, engine="pyogrio", driver="ESRI Shapefile")
    # Confirm the actual on-disk DBF, not just the source Python dictionary.
    attributes = pyogrio.read_dataframe(source, read_geometry=False)
    assert attributes.iloc[0]["geometry"] == "business attribute"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in directory.iterdir():
            archive.write(path, path.name)
    result = upload_results(regression_client, "collision.zip", output.getvalue())
    feature = result["features"][0]
    assert feature["properties"] == {"geometry": "business attribute", "value": 42}
    assert feature["geometry"] == {"type": "Point", "coordinates": [500000, 1500000]}


def test_kml_properties_are_lossless(regression_client):
    body = kml_document(
        '<Placemark id="first"><name>Feature title</name><description>Description</description>'
        "<address>Address</address><ExtendedData>"
        '<Data name="name"><value>Business name</value></Data>'
        '<Data name="owner"><value>Alice</value></Data>'
        '<Data name="owner"><value>Bob</value></Data>'
        '<Data name="extended_data"><value>Reserved field</value></Data>'
        '<SchemaData schemaUrl="#first"><SimpleData name="owner">Carol</SimpleData></SchemaData>'
        '<SchemaData schemaUrl="#second"><SimpleData name="owner">Dave</SimpleData></SchemaData>'
        "</ExtendedData><Point><coordinates>81,13</coordinates></Point></Placemark>"
        '<Placemark id="second"><name>Second feature</name><ExtendedData>'
        '<Data name="code"><value>42</value></Data></ExtendedData>'
        "<Point><coordinates>81.001,13</coordinates></Point></Placemark>"
    )
    result = upload_results(regression_client, "properties.kml", body)
    first, second = result["features"]
    props = first["properties"]
    assert props["name"] == "Feature title"
    assert props["description"] == "Description"
    assert props["address"] == "Address"
    assert props["owner"] == "Alice"  # Existing noncolliding flat alias survives.
    assert [entry["value"] for entry in props["extended_data"]] == [
        "Business name",
        "Alice",
        "Bob",
        "Reserved field",
        "Carol",
        "Dave",
    ]
    assert [e["schema_url"] for e in props["extended_data"] if e["kind"] == "SimpleData"] == [
        "#first",
        "#second",
    ]
    assert second["properties"]["name"] == "Second feature"
    assert second["properties"]["code"] == "42"
    assert len(second["properties"]["extended_data"]) == 1


@pytest.mark.parametrize("epsg", [4326, 3857])
def test_local_geographic_and_mercator_lines(regression_client, tmp_path, epsg):
    geographic = LineString([(81, 13), (81.001, 13)])
    geometry = transform(Transformer.from_crs(4326, epsg, always_xy=True).transform, geographic)
    result = upload_results(
        regression_client, "local.zip", shapefile_zip(tmp_path / "local", geometry, epsg)
    )
    feature = result["features"][0]
    assert feature["measurement_error"] is None
    assert feature["measurement"]["unit"] == "meters"
    assert feature["measurement"]["value"] == pytest.approx(
        Geod(ellps="WGS84").geometry_length(geographic), rel=0.002
    )


@pytest.mark.parametrize(
    "geometry,epsg",
    [
        (LineString([(20026376.393709917, 0), (-20026376.393709917, 0)]), 3857),
        (LineString([(179.9, 10), (-179.9, 10)]), 4326),
        (LineString([(0, 0), (20, 0)]), 4326),
        (
            transform(
                Transformer.from_crs(4326, 3857, always_xy=True).transform,
                LineString([(0, 0), (20, 0)]),
            ),
            3857,
        ),
    ],
)
def test_unsafe_geometry_has_no_measurement(regression_client, tmp_path, geometry, epsg):
    result = upload_results(
        regression_client, "unsafe.zip", shapefile_zip(tmp_path / "unsafe", geometry, epsg)
    )
    feature = result["features"][0]
    assert feature["geometry"] is not None
    assert feature["measurement"] is None
    assert feature["measurement_error"]
    assert any(word in feature["measurement_error"].lower() for word in ("extent", "dateline"))


@pytest.mark.parametrize("multi", [False, True])
@pytest.mark.parametrize("epsg", [4326, 3857, 32644])
def test_local_polygons_keep_correct_area(regression_client, tmp_path, multi, epsg):
    polygon = metric_polygon()
    geometry = MultiPolygon([polygon, translate(polygon, xoff=200)]) if multi else polygon
    geometry = transform(Transformer.from_crs(32644, epsg, always_xy=True).transform, geometry)
    result = upload_results(
        regression_client, "polygon.zip", shapefile_zip(tmp_path / "polygon", geometry, epsg)
    )
    assert result["features"][0]["measurement_error"] is None
    assert result["features"][0]["geometry_type"] == ("MultiPolygon" if multi else "Polygon")
    assert result["features"][0]["measurement"]["value"] == pytest.approx(
        20000 if multi else 10000, abs=0.001
    )


def grad_crs():
    definition = CRS.from_epsg(4326).to_json_dict()
    definition.pop("id")
    definition["name"] = "WGS84 in grads"
    for axis in definition["coordinate_system"]["axis"]:
        axis["unit"] = {"type": "AngularUnit", "name": "grad", "conversion_factor": math.pi / 200}
    return CRS.from_json_dict(definition)


@pytest.mark.parametrize("crs,point", [(4326, Point(0, 85.5)), (grad_crs(), Point(0, 95))])
def test_angular_units_normalized(regression_client, tmp_path, crs, point):
    result = upload_results(
        regression_client, "angular.zip", shapefile_zip(tmp_path / "angular", point, crs)
    )
    assert result["measurement_crs"] == "EPSG:32661"
    assert result["features"][0]["measurement_error"] is None
    assert result["features"][0]["geometry"]["coordinates"] == list(point.coords[0])


@pytest.mark.parametrize(
    "crs,point",
    [
        (4326, Point(0, 91)),
        (4326, Point(181, 0)),
        (grad_crs(), Point(0, 101)),
        (grad_crs(), Point(201, 0)),
    ],
)
def test_invalid_angular_coordinates_rejected(regression_client, tmp_path, crs, point):
    contents = shapefile_zip(tmp_path / "invalid", point, crs)
    response = regression_client.post("/api/files/", files={"file": ("invalid.zip", contents)})
    assert response.status_code == 400, response.text
    assert "coordinates" in response.json()["detail"].lower()


def test_unknown_xml_encoding_is_client_error(regression_client):
    body = kml_document("<Placemark><Point><coordinates>81,13</coordinates></Point></Placemark>")
    body = body.replace(b"UTF-8", b"UNKNOWN-ENCODING")
    response = regression_client.post("/api/files/", files={"file": ("encoding.kml", body)})
    assert response.status_code == 400, response.text
    assert "Malformed KML" in response.json()["detail"]


def test_grad_lines_are_measured_after_normalization(regression_client, tmp_path):
    geographic = LineString([(81, 13), (81.001, 13)])
    crs = grad_crs()
    geometry = transform(Transformer.from_crs(4326, crs, always_xy=True).transform, geographic)
    result = upload_results(
        regression_client, "grad-line.zip", shapefile_zip(tmp_path / "grad-line", geometry, crs)
    )["features"][0]
    assert result["measurement_error"] is None
    assert result["measurement"]["value"] == pytest.approx(
        Geod(ellps="WGS84").geometry_length(geographic), rel=0.002
    )


def test_nested_empty_part_is_not_discarded(regression_client):
    body = kml_document(
        "<Placemark><MultiGeometry><MultiGeometry><Point><coordinates/></Point>"
        "</MultiGeometry><Point><coordinates>81,13</coordinates></Point>"
        "</MultiGeometry></Placemark>"
    )
    feature = upload_results(regression_client, "empty-part.kml", body)["features"][0]
    assert feature["geometry_type"] == "GeometryCollection"
    assert len(feature["geometry"]["geometries"]) == 2
    assert feature["measurement"] is None
    assert "GeometryCollection" in feature["measurement_error"]


def test_nested_homogeneous_multigeometry_measures_all_parts(regression_client):
    start, end = to_wgs84(Point(500000, 1500000)), to_wgs84(Point(500100, 1500000))
    coords = f"{start.x},{start.y} {end.x},{end.y}"
    line = f"<LineString><coordinates>{coords}</coordinates></LineString>"
    body = kml_document(
        f"<Placemark><MultiGeometry><MultiGeometry><MultiGeometry>{line}</MultiGeometry>"
        f"{line}</MultiGeometry>{line}</MultiGeometry></Placemark>"
    )
    result = upload_results(regression_client, "nested.kml", body)["features"][0]
    assert result["geometry_type"] == "MultiLineString"
    assert len(result["geometry"]["coordinates"]) == 3
    assert result["measurement_error"] is None
    assert result["measurement"]["value"] == pytest.approx(300, abs=0.001)


@pytest.mark.parametrize("namespace", ["", "urn:wrong"])
def test_wrong_namespace_geometry_rejected(regression_client, namespace):
    body = kml_document(
        f'<Placemark><MultiGeometry><Point xmlns="{namespace}">'
        "<coordinates>81,13</coordinates></Point></MultiGeometry></Placemark>"
    )
    response = regression_client.post("/api/files/", files={"file": ("namespace.kml", body)})
    assert response.status_code == 400, response.text
    assert "namespace" in response.json()["detail"]
