import asyncio
import io
import json
import stat
import zipfile

import pytest

from tests.helpers import kml_document, zip_entries


@pytest.mark.parametrize(
    "filename,body,mime",
    [
        ("file.txt", b"abc", "text/plain"),
        ("file.kml", b"not XML", "application/xml"),
        ("file.kml", b"", "application/xml"),
        ("file.zip", b"not a zip", "application/zip"),
        ("file.kml", b"<root/>", "application/xml"),
        ("file.kml", kml_document(""), "application/xml"),
        ("file.kml", kml_document("<Placemark/>"), "image/png"),
    ],
)
def test_invalid_uploads_have_clean_errors_and_no_artifacts(
    client,
    settings,
    filename,
    body,
    mime,
):
    response = client.post("/api/files/", files={"file": (filename, body, mime)})
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)
    assert "Traceback" not in response.text
    assert str(settings.upload_dir) not in response.text
    assert not list(settings.upload_dir.iterdir())
    assert not list(settings.processed_dir.iterdir())


@pytest.mark.parametrize(
    "entry",
    ["../escape.shp", "/escape.shp", "C:/escape.shp", "nested/../../escape.shp", "..\\escape.shp"],
)
def test_zip_path_traversal_rejected(client, entry):
    response = client.post(
        "/api/files/", files={"file": ("evil.zip", zip_entries({entry: b"evil"}))}
    )
    assert response.status_code == 400
    assert "Unsafe" in response.json()["detail"]


def test_zip_symlink_rejected(client):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        info = zipfile.ZipInfo("link.shp")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "../../target")
    response = client.post("/api/files/", files={"file": ("evil.zip", output.getvalue())})
    assert response.status_code == 400
    assert "Unsafe" in response.json()["detail"]


@pytest.mark.parametrize(
    "entries,expected",
    [
        ({"parcel.shp": b"x"}, "Missing Shapefile components"),
        ({"other.txt": b"x"}, "exactly one"),
        ({"a.shp": b"x", "b.shp": b"x"}, "exactly one"),
        ({"a.shp": b"x", "A.SHP": b"y"}, "duplicate"),
        ({"a.shp": b"x", "a.shx": b"x", "a.dbf": b"x", "a.prj": b"x"}, "corrupted"),
    ],
)
def test_archive_structure(client, entries, expected):
    response = client.post("/api/files/", files={"file": ("bad.zip", zip_entries(entries))})
    assert response.status_code == 400
    assert expected in response.json()["detail"]


def test_zip_bomb_ratio_rejected(client):
    bomb = zip_entries({"huge.txt": b"0" * 100000})
    response = client.post("/api/files/", files={"file": ("bomb.zip", bomb)})
    assert response.status_code == 400
    assert "compression ratio" in response.json()["detail"]


def test_archive_entry_and_expansion_limits(client, settings):
    settings.max_archive_members = 2
    response = client.post(
        "/api/files/",
        files={
            "file": (
                "bad.zip",
                zip_entries(
                    {
                        "a": b"x",
                        "b": b"x",
                        "c": b"x",
                    }
                ),
            )
        },
    )
    assert "too many" in response.json()["detail"]
    settings.max_compression_ratio = 100000
    response = client.post(
        "/api/files/",
        files={
            "file": (
                "bad.zip",
                zip_entries(
                    {
                        "a": b"x" * (settings.max_archive_bytes + 1),
                    }
                ),
            )
        },
    )
    assert response.status_code == 400
    assert "expansion" in response.json()["detail"]


def test_upload_size_and_entire_request_size(client):
    response = client.post("/api/files/", files={"file": ("big.kml", b"x" * (1024 * 1024 + 1))})
    assert response.status_code == 413
    assert "size limit" in response.json()["detail"]
    response = client.post("/api/files/", content=b"x" * (2 * 1024 * 1024 + 1))
    assert response.status_code == 413


def test_chunked_upload_is_also_bounded(client):
    def chunks():
        yield (
            b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="big.kml"\r\n\r\n'
        )
        for _ in range(34):
            yield b"x" * 65536
        yield b"\r\n--boundary--\r\n"

    response = client.post(
        "/api/files/",
        content=chunks(),
        headers={
            "Content-Type": "multipart/form-data; boundary=boundary",
        },
    )
    assert response.status_code == 413, response.text
    assert "size limit" in response.json()["detail"]


def test_stream_limit_across_separate_asgi_messages(client):
    """Unlike TestClient's body generator, this really sends separate receive messages."""
    messages = [
        {
            "type": "http.request",
            "body": (
                b'--boundary\r\nContent-Disposition: form-data; name="file"; '
                b'filename="big.kml"\r\n\r\n'
            ),
            "more_body": True,
        },
        *[{"type": "http.request", "body": b"x" * 65536, "more_body": True} for _ in range(34)],
        {"type": "http.request", "body": b"\r\n--boundary--\r\n", "more_body": False},
    ]
    sent = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/files/",
        "raw_path": b"/api/files/",
        "query_string": b"",
        "root_path": "",
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "headers": [(b"content-type", b"multipart/form-data; boundary=boundary")],
    }
    asyncio.run(client.app(scope, receive, send))
    assert sent[0]["status"] == 413
    body = b"".join(message.get("body", b"") for message in sent[1:])
    assert json.loads(body) == {"detail": "Request body exceeds the size limit."}
    assert messages  # The rest of the oversized body was not consumed.


def test_uppercase_shapefile_components(client, zip_bytes):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as original:
        entries = {item.filename.upper(): original.read(item) for item in original.infolist()}
    response = client.post("/api/files/", files={"file": ("survey.zip", zip_entries(entries))})
    assert response.status_code == 201, response.text
    results = client.get(response.headers["location"] + "measurements/").json()
    assert results["features"][0]["measurement"]["value"] == 10000


def test_unreadable_shapefile_crs(client, zip_bytes):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as original:
        entries = {item.filename: original.read(item) for item in original.infolist()}
    entries["nested/parcel.prj"] = b"THIS IS NOT A CRS"
    response = client.post("/api/files/", files={"file": ("survey.zip", zip_entries(entries))})
    assert response.status_code == 422, response.text
    assert "CRS" in response.json()["detail"]


def test_xml_entities_are_forbidden(client):
    body = (
        b'<!DOCTYPE kml [<!ENTITY secret SYSTEM "file:///etc/passwd">]>'
        b'<kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><name>&secret;</name></Placemark></kml>'
    )
    response = client.post("/api/files/", files={"file": ("evil.kml", body)})
    assert response.status_code == 400
    assert "Malformed KML" in response.json()["detail"]


@pytest.mark.parametrize(
    "geometry",
    [
        "<Point><coordinates>181,0</coordinates></Point>",
        "<Point><coordinates>80,91</coordinates></Point>",
        "<Point><coordinates>nan,0</coordinates></Point>",
        "<Point><coordinates>1,2 3,4</coordinates></Point>",
        "<Point/>",
        "<LineString><coordinates>1,2</coordinates></LineString>",
        "<Polygon/>",
        "<Polygon><outerBoundaryIs><LinearRing><coordinates>1,1 2,1 2,2</coordinates>"
        "</LinearRing></outerBoundaryIs></Polygon>",
        "<Model/>",
        "<LinearRing/>",
    ],
)
def test_malformed_kml_geometries_rejected(client, geometry):
    body = kml_document("<Placemark>" + geometry + "</Placemark>")
    response = client.post("/api/files/", files={"file": ("bad.kml", body)})
    assert response.status_code == 400
    assert "detail" in response.json()


def test_network_links_rejected(client):
    body = kml_document(
        "<NetworkLink><Link><href>https://example.com/remote.kml</href></Link></NetworkLink>"
    )
    response = client.post("/api/files/", files={"file": ("remote.kml", body)})
    assert response.status_code == 400
    assert "network links" in response.json()["detail"]


def test_feature_and_coordinate_limits(client, settings, kml_bytes):
    settings.max_features = 1
    response = client.post("/api/files/", files={"file": ("survey.kml", kml_bytes)})
    assert response.status_code == 400
    assert "feature limit" in response.json()["detail"]
    settings.max_features = 100
    settings.max_coordinates = 1
    response = client.post("/api/files/", files={"file": ("survey.kml", kml_bytes)})
    assert response.status_code == 400
    assert "coordinate limit" in response.json()["detail"]


def test_storage_failure_cleans_files_and_hides_details(client, settings, kml_bytes, monkeypatch):
    def fail(*args):
        raise OSError("secret path /private/credentials")

    monkeypatch.setattr(client.app.state.file_service.repository, "save", fail)
    response = client.post("/api/files/", files={"file": ("survey.kml", kml_bytes)})
    assert response.status_code == 500
    assert response.json() == {"detail": "An internal processing error occurred."}
    assert not list(settings.upload_dir.iterdir())
    assert not list(settings.processed_dir.iterdir())


def test_missing_processed_artifact_returns_clean_500(client, settings, kml_bytes):
    result = client.post("/api/files/", files={"file": ("survey.kml", kml_bytes)}).json()
    (settings.processed_dir / (result["id"] + ".json")).unlink()
    response = client.get(f"/api/files/{result['id']}/measurements/")
    assert response.status_code == 500
    assert response.json() == {"detail": "An internal processing error occurred."}
