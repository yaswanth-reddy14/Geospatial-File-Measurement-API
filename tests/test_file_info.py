from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import create_app


def test_metadata_and_persistence_across_restart(client, settings, kml_bytes):
    uploaded = client.post("/api/files/", files={"file": ("survey.kml", kml_bytes)}).json()
    assert client.get(f"/api/files/{uploaded['id']}/").json() == uploaded
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get(f"/api/files/{uploaded['id']}/").json() == uploaded
        assert (
            len(restarted.get(f"/api/files/{uploaded['id']}/measurements/").json()["features"]) == 3
        )


def test_unknown_id_and_invalid_id(client):
    for suffix in ("", "measurements/"):
        response = client.get(f"/api/files/{uuid4()}/{suffix}")
        assert response.status_code == 404
        assert response.json() == {"detail": "File not found."}
    assert client.get("/api/files/not-a-uuid/").status_code == 422
