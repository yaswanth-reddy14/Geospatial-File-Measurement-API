"""Exercise a live Uvicorn server, or use --base-url to check an existing server."""

import argparse
import math
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from generate_samples import generate_zip

ROOT = Path(__file__).resolve().parents[1]


def wait_for_server(base_url: str, process: subprocess.Popen | None) -> None:
    for _ in range(100):
        if process is not None and process.poll() is not None:
            raise RuntimeError("Uvicorn exited before it was ready")
        try:
            response = httpx.get(base_url + "/health", timeout=1)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise RuntimeError("Server did not become healthy within 20 seconds")


def exercise_server(base_url: str, directory: Path) -> None:
    archive = directory / "survey.zip"
    generate_zip(archive)
    with httpx.Client(base_url=base_url, timeout=30) as client:
        assert client.get("/health").json() == {"status": "ok"}
        for path, mime, count in [
            (ROOT / "examples" / "survey.kml", "application/vnd.google-earth.kml+xml", 3),
            (archive, "application/zip", 1),
        ]:
            with path.open("rb") as source:
                uploaded = client.post("/api/files/", files={"file": (path.name, source, mime)})
            assert uploaded.status_code == 201, uploaded.text
            metadata = uploaded.json()
            assert metadata["feature_count"] == count
            location = uploaded.headers["location"]
            assert client.get(location).json() == metadata
            response = client.get(location + "measurements/")
            assert response.status_code == 200, response.text
            results = response.json()
            assert results["measurement_crs"] == "EPSG:32644"
            measurement = results["features"][0]["measurement"]
            assert measurement["unit"] == "square_meters"
            assert measurement["value"] > 1000
            if path.suffix == ".zip":
                assert math.isclose(measurement["value"], 10000, abs_tol=1e-6)
            else:
                assert results["crs"] == "EPSG:4326"
                assert results["features"][1]["measurement"]["unit"] == "meters"
                assert results["features"][2]["measurement"] is None
            print(f"PASS {path.suffix}: upload, metadata, geometry, CRS, and measurements")
        assert "swagger-ui" in client.get("/docs").text
        assert "redoc" in client.get("/redoc").text
        assert "/api/files/" in client.get("/openapi.json").json()["paths"]
        print("PASS health, Swagger, ReDoc, and OpenAPI")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", help="Existing server, e.g. http://127.0.0.1:8000")
    parser.add_argument(
        "--regressions", action="store_true", help="Also run audit regressions over real HTTP"
    )
    arguments = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="geospatial-smoke-") as temp:
        directory = Path(temp)
        process = None
        base_url = arguments.base_url
        log_path = directory / "server.log"
        with log_path.open("w", encoding="utf-8") as log:
            try:
                if not base_url:
                    with socket.socket() as listener:
                        listener.bind(("127.0.0.1", 0))
                        port = listener.getsockname()[1]
                    base_url = f"http://127.0.0.1:{port}"
                    environment = os.environ | {
                        "UPLOAD_DIR": str(directory / "uploads"),
                        "PROCESSED_DIR": str(directory / "processed"),
                        "DATABASE_URL": "sqlite:///" + str(directory / "app.db"),
                    }
                    process = subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "uvicorn",
                            "app.main:app",
                            "--host",
                            "127.0.0.1",
                            "--port",
                            str(port),
                        ],
                        cwd=ROOT,
                        env=environment,
                        stdout=log,
                        stderr=log,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    )
                wait_for_server(base_url.rstrip("/"), process)
                exercise_server(base_url.rstrip("/"), directory)
                if arguments.regressions:
                    regressions = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "pytest",
                            "-q",
                            "tests/test_audit_regressions.py",
                            "--regression-base-url",
                            base_url.rstrip("/"),
                        ],
                        cwd=ROOT,
                        capture_output=True,
                        text=True,
                        timeout=180,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    )
                    print(regressions.stdout, end="")
                    if regressions.stderr:
                        print(regressions.stderr, file=sys.stderr, end="")
                    regressions.check_returncode()
            except Exception:
                if process is not None:
                    log.flush()
                    print(log_path.read_text(encoding="utf-8"), file=sys.stderr)
                raise
            finally:
                if process is not None:
                    if os.name == "nt":
                        # A Windows venv python.exe can be a redirector with a child interpreter.
                        subprocess.run(
                            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                            check=False,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW,
                        )
                    else:
                        process.terminate()
                    process.wait(timeout=10)


if __name__ == "__main__":
    main()
