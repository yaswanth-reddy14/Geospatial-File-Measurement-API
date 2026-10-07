import json
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest

from app.schemas.file import MeasurementsResponse


@pytest.mark.parametrize(
    "format,mime,count",
    [
        ("kml", "application/vnd.google-earth.kml+xml", 3),
        ("zip", "application/zip", 1),
    ],
)
def test_upload_and_measurements(client, kml_bytes, zip_bytes, format, mime, count):
    contents = kml_bytes if format == "kml" else zip_bytes
    response = client.post("/api/files/", files={"file": ("survey." + format, contents, mime)})
    assert response.status_code == 201, response.text
    metadata = response.json()
    assert UUID(metadata["id"])
    assert metadata["feature_count"] == count
    assert metadata["status"] == "COMPLETED"
    assert metadata["crs"] == ("EPSG:4326" if format == "kml" else "EPSG:32644")
    assert metadata["created_at"].endswith("Z")
    assert response.headers["location"] == f"/api/files/{metadata['id']}/"
    measurements_response = client.get(response.headers["location"] + "measurements/")
    assert measurements_response.status_code == 200
    result = MeasurementsResponse.model_validate(measurements_response.json())
    assert result.measurement_crs == "EPSG:32644"
    assert result.features[0].properties["name"] == "Parcel A"
    assert result.features[0].measurement.unit == "square_meters"
    assert result.features[0].measurement.value == pytest.approx(10000, abs=0.001)
    if format == "kml":
        assert result.features[0].properties["owner"] == "Alice"
        assert result.features[0].source_feature_id == "parcel"
        assert result.features[1].measurement.value == pytest.approx(100, abs=0.001)
        assert result.features[1].measurement.unit == "meters"
        assert result.features[2].measurement is None
        assert result.features[0].geometry["coordinates"][0][0][0] == pytest.approx(81)
    else:
        assert result.features[0].properties["score"] == 7
        assert result.features[0].geometry["coordinates"][0][0] == [500000, 1500000]
    json.dumps(result.model_dump(mode="json"), allow_nan=False)


def test_filename_sanitization(client, kml_bytes, settings):
    response = client.post("/api/files/", files={"file": ("../../unsafe?.KML", kml_bytes)})
    assert response.status_code == 201
    assert response.json()["filename"] == "unsafe_.KML"
    paths = list(settings.upload_dir.iterdir())
    assert len(paths) == 1
    assert paths[0].name == response.json()["id"] + ".kml"


def test_concurrent_uploads_have_independent_results(client, kml_bytes):
    def upload(_):
        return client.post("/api/files/", files={"file": ("survey.kml", kml_bytes)})

    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(upload, range(3)))
    assert all(response.status_code == 201 for response in responses)
    ids = {response.json()["id"] for response in responses}
    assert len(ids) == 3
    for file_id in ids:
        assert client.get(f"/api/files/{file_id}/measurements/").json()["file_id"] == file_id
