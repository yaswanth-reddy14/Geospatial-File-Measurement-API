import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.helpers import mixed_kml, shapefile_zip


def pytest_addoption(parser):
    parser.addoption(
        "--regression-base-url", help="Run audit regressions against a live HTTP server"
    )


@pytest.fixture
def regression_client(request, client):
    url = request.config.getoption("--regression-base-url")
    if url:
        with httpx.Client(base_url=url, timeout=30) as live_client:
            yield live_client
    else:
        yield client


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        upload_dir=tmp_path / "uploads",
        processed_dir=tmp_path / "processed",
        database_url="sqlite:///" + str(tmp_path / "app.db"),
        max_upload_size_mb=1,
        max_archive_size_mb=2,
        max_compression_ratio=100,
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def kml_bytes():
    return mixed_kml()


@pytest.fixture
def zip_bytes(tmp_path):
    return shapefile_zip(tmp_path / "shape")
