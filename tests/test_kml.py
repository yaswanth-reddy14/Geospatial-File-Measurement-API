import pytest

from tests.helpers import kml_document


@pytest.mark.parametrize(
    "geometry,expected_type",
    [
        (
            "<Point><coordinates>81,13</coordinates></Point>"
            "<Point><coordinates>81.001,13</coordinates></Point>",
            "MultiPoint",
        ),
        (
            "<LineString><coordinates>81,13 81.001,13</coordinates></LineString>"
            "<LineString><coordinates>81,13.001 81.001,13.001</coordinates></LineString>",
            "MultiLineString",
        ),
        (
            "<Polygon><outerBoundaryIs><LinearRing><coordinates>"
            "81,13 81.001,13 81.001,13.001 81,13</coordinates>"
            "</LinearRing></outerBoundaryIs></Polygon>",
            "MultiPolygon",
        ),
        (
            "<Point><coordinates>81,13</coordinates></Point>"
            "<LineString><coordinates>81,13 81.001,13</coordinates></LineString>",
            "GeometryCollection",
        ),
    ],
)
def test_multi_geometry_ingestion(client, geometry, expected_type):
    body = kml_document("<Placemark><MultiGeometry>" + geometry + "</MultiGeometry></Placemark>")
    response = client.post("/api/files/", files={"file": ("multi.kml", body)})
    assert response.status_code == 201, response.text
    result = client.get(response.headers["location"] + "measurements/").json()["features"][0]
    assert result["geometry_type"] == expected_type
    if expected_type in {"MultiPolygon", "MultiLineString"}:
        assert result["measurement"]["value"] > 0
    else:
        assert result["measurement"] is None
    if expected_type == "GeometryCollection":
        assert "GeometryCollection" in result["measurement_error"]


def test_empty_null_and_invalid_kml_are_reported_per_feature(client):
    body = kml_document(
        '<Placemark id="empty"><Point><coordinates/></Point></Placemark>'
        '<Placemark id="null"><name>No location</name></Placemark>'
        '<Placemark id="invalid"><Polygon><outerBoundaryIs><LinearRing><coordinates>'
        "81,13 81.001,13.001 81.001,13 81,13.001 81,13"
        "</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>"
    )
    response = client.post("/api/files/", files={"file": ("special.kml", body)})
    assert response.status_code == 201
    results = client.get(response.headers["location"] + "measurements/").json()
    assert results["measurement_crs"] is None
    assert results["features"][0]["geometry_type"] == "Point"
    assert results["features"][0]["geometry"] is None
    assert results["features"][1]["geometry_type"] is None
    assert results["features"][2]["geometry"]["type"] == "Polygon"
    assert "Invalid geometry" in results["features"][2]["measurement_error"]


def test_collection_with_mixed_2d_and_3d_parts_preserves_both(client):
    body = kml_document(
        "<Placemark><MultiGeometry><Point><coordinates>81,13</coordinates></Point>"
        "<LineString><coordinates>81,13,0 81.001,13,100</coordinates></LineString>"
        "</MultiGeometry></Placemark>"
    )
    response = client.post("/api/files/", files={"file": ("mixed.kml", body)})
    assert response.status_code == 201, response.text
    feature = client.get(response.headers["location"] + "measurements/").json()["features"][0]
    assert feature["geometry_type"] == "GeometryCollection"
    assert len(feature["geometry"]["geometries"][0]["coordinates"]) == 2
    assert len(feature["geometry"]["geometries"][1]["coordinates"][0]) == 3
    assert "GeometryCollection" in feature["measurement_error"]
