# Fix validation and second compliance audit

Validated on 7 October 2026 after implementing the independent audit fixes.
No commits, pushes or GitHub repository creation were performed.

## Executed results

| Check | Result |
| --- | --- |
| Windows Python 3.14.8, pytest -q | **118 passed, 0 failed** |
| Windows coverage run | **118 passed; 96%** (685 statements, 25 uncovered) |
| Linux Python 3.12.15, complete suite | **118 passed, 0 failed** |
| Original test files | Hashes unchanged except additive live-client support in conftest.py |
| Ruff check / format check | Passed; 38 Python files formatted |
| pip check | No broken requirements |
| Local Uvicorn HTTP smoke | KML, ZIP, metadata, measurements, health, docs and OpenAPI passed |
| Local HTTP audit regressions | **26 passed** |
| docker compose build --no-cache | Passed; runtime dependencies freshly installed |
| Compose startup / health | Healthy on host port 18001 |
| Docker HTTP smoke | KML, ZIP, metadata, measurements, health, docs and OpenAPI passed |
| Docker HTTP audit regressions | **26 passed** |
| Actual Docker process restart | Existing KML/ZIP metadata and results returned 200 after readiness |
| Container identity | Non-root UID/GID 10001 |
| Clean image application bytecode scan | No .pyc, .pyo, .pyd or __pycache__ under /app/app |
| Compose configuration overrides | Every MAX_* setting and LOG_LEVEL forwarded correctly |
| Lightweight credential-pattern scan | No matches |
| Local data directories | Only .gitkeep files |

Both platforms emit the existing upstream Starlette/AnyIO TestClient deprecation
warning. Newly introduced NumPy scalar-conversion warnings were corrected before
the final runs. A first restart probe ran before Uvicorn was ready; repeating after
health readiness verified persistence.

Linux tests used the clean production image with tests mounted read-only and
pytest/httpx installed into /tmp/testdeps in a disposable container. Development
packages were not added to the production image.

## Fixed counterexamples

- Actual DBF geometry="business attribute" and value=42 survive upload while
  top-level geometry remains the actual Point.
- Standard KML name="Feature title" and custom name="Business name" both survive.
  Duplicate custom names, reserved names and schema identities are retained.
- The world-spanning EPSG:3857 line returns null measurement and an explicit
  unsafe-extent/projection-boundary error, rather than approximately 22 km.
- Local EPSG:4326/EPSG:3857 lines agree with independent geodesic references within
  0.2%; local polygon areas retain known values within 0.001 square metres.
- Dateline and excessive multi-zone extents return null measurements and errors.
- Unknown XML encoding returns HTTP 400.
- A geographic Point at (0,95) grads is accepted as 85.5 degrees north; grad-based
  line measurement and invalid angular coordinate rejection are tested.
- Nested homogeneous KML lines aggregate to 300 metres; empty parts are preserved.
- Recognizable geometry in an empty/incorrect XML namespace returns HTTP 400.

## Second audit against the original assignment

| Requirement | Status | Evidence |
| --- | --- | --- |
| FastAPI backend | PASS | app/main.py:create_app |
| POST /api/files/, multipart KML and ZIP | PASS | files.py:upload_file; both live smoke runs |
| Shapefile extraction and component validation | PASS | archive_service.py:extract_shapefile; validation tests |
| KML feature extraction | PASS | kml_service.py:read_kml; KML/audit tests |
| Feature index/source ID | PASS | FeatureMeasurement; upload tests |
| Geometry type and original geometry | PASS | measure_feature; API assertions |
| Source CRS exposed | PASS | Global dataset CRS in metadata/results; one source CRS per dataset |
| Properties preserved | PASS | Raw DBF arrays; canonical KML records; collision API regressions |
| Unsupported geometry handled gracefully | PASS | GeometryCollection/null/empty/invalid tests |
| Polygon area | PASS | Numerical square/hole tests and API polygon cases |
| LineString length | PASS | Known 5 m/100 m tests; independent references; unsafe-case rejection |
| Point needs no measurement | PASS | Point/MultiPoint tests |
| Geographic coordinates transformed before calculation | PASS | measure_dataset; geographic known-value tests |
| Defensible projected CRS selection | PASS | UTM/UPS, angular normalization, envelope guards and explicit rejection |
| GET /api/files/{id}/ | PASS | Metadata, 404 and real restart checks |
| GET /api/files/{id}/measurements/ | PASS | Typed schemas and live retrieval |
| README local setup | PASS | Setup section; local server execution |
| README endpoints, requests and responses | PASS | API section and example comparison |
| README structure and processing flow | PASS | Architecture diagram and Design Decisions |
| README measurement flow and CRS handling | PASS | CRS Handling and geometry behavior sections |
| README decisions and alternatives | PASS | Design Decisions and Alternatives |
| README learning | PASS | Learning section |
| README future scope | PASS | Future Scope section |
| Public GitHub repository | PASS | Published by the owner at https://github.com/yaswanth-reddy14/Geospatial-File-Measurement-API |

PASS for CRS handling means the documented local planar strategy meets the assignment,
not universal geospatial accuracy. Subsequent clean-environment checks are recorded
in the CI investigation below. Hosted GitHub Actions steps have not executed because
of an account lock. Docker dependencies were installed without cached build steps.

## Remaining limitations and risks

- KML support is the documented subset; tracks, models and links are rejected.
- UTM/UPS values include projection distortion and are not geodesic measurements.
- Bounded projected-envelope sampling is conservative screening, not proof for
  every custom projection; it can reject disconnected or irregular datasets.
- Existing vertices are transformed; arbitrary curved/geodesic path preservation
  and global measurements require specialized handling outside current scope.
- Supplied metre-based projections other than excluded Mercator CRSs are trusted;
  their suitability and area of use are not certified.
- Crash-orphan reconciliation, authentication, rate limiting and storage quotas
  remain future deployment work. This was not a full vulnerability assessment.
- The repository is now public. Its first hosted CI run was blocked before any
  steps executed by a GitHub account billing lock; see the CI investigation below.

## Repeat the checks

```bash
python -m pytest -q
python -m pytest --cov=app --cov-report=term-missing
python -m ruff check .
python -m ruff format --check .
python scripts/smoke_test.py --regressions
docker compose build --no-cache
docker compose up -d --wait
python scripts/smoke_test.py --base-url http://127.0.0.1:8000 --regressions
docker compose down
```

Choose a free port with API_PORT as described in README. Live regressions create
persistent uploads on an existing server; use disposable storage for validation.
The verification project geospatial-fix-verification used its own volume/network;
these were removed after validation. Unrelated running services were untouched.
The clean image remains available. Git ignores local runtime/test artifacts, and
Docker recursively excludes application bytecode from its build context.

## GitHub Actions investigation

The owner published commit `7a81abe` after the implementation audit.
[Run 37631844117](https://github.com/yaswanth-reddy14/Geospatial-File-Measurement-API/actions/runs/37631844117)
failed before any checkout, Python setup, dependency installation or Docker build.
Both the Windows and Docker annotations state that the account is locked due to a
billing issue. Ubuntu's annotation explicitly identifies matrix cancellation after
the Windows job failed. The public jobs API confirms empty step lists for all three.
This is a GitHub account issue, not an observed application or dependency failure.
The account owner must resolve the lock before hosted jobs can execute.

Workflow changes preserve Windows Python 3.14 and Ubuntu Python 3.12, retain all
lint/format/test checks, disable matrix fail-fast, upgrade pip, check dependencies
and explicitly hash both requirements files for pip caching. Separate installation
steps preserve native-command exit codes on Windows. Docker now builds without
cached layers, waits for actual container health, runs real API smoke tests and
all audit regressions on port 18001, prints logs and always removes disposable data.
No continue-on-error, skipped tests, dependency downgrades or application changes
were introduced. Actionlint 1.7.7 validated the revised workflow successfully.

Fresh installations used the committed requirements rather than installed packages
from the working project's virtual environment. Windows used a new temporary
Python 3.14.8 environment with system site-packages disabled; imported package
locations were verified against that environment. Linux used Python 3.12.15 in a
disposable Debian Bookworm container with a new virtual environment and a read-only
source mount. This verifies Linux compatibility, not execution on a hosted Ubuntu
runner. Fiona is neither required nor installed: KML uses the secure XML parser.

| Fresh-environment check | Windows Python 3.14.8 | Linux Python 3.12.15 |
| --- | --- | --- |
| Requirements installed from scratch, pip cache disabled | Passed | Passed |
| pytest -q | 118 passed | 118 passed |
| Coverage run | 118 passed; 96%, 685 statements / 25 missed | 118 passed; 96%, 706 statements / 25 missed |
| Ruff lint / format | Passed / Passed | Passed / Passed |
| pip check | No broken requirements | No broken requirements |
| Live KML / ZIP smoke and all required GET endpoints | Passed | Passed |
| Live audit regressions | 26 passed | 26 passed |

The coverage statement counts differ between interpreter versions; both report 96%.
The existing upstream Starlette/AnyIO deprecation warning appears on both platforms.

The production Compose image was also rebuilt with `--no-cache` during this
investigation. Fresh binary dependencies installed successfully, the service became
healthy using `up -d --wait --wait-timeout 60`, and the fresh Windows environment
ran KML/ZIP HTTP smoke checks plus all 26 audit regressions against the container.
Imports inside the image confirmed GeoPandas 1.1.1, Shapely 2.1.2, PyProj 3.7.2 and
pyogrio 0.12.1. The verification project, network and volume were removed afterward;
unrelated services and the original .venv were preserved. Automatic execution policy
blocked recursive deletion of the temporary Windows environment, which remains
outside the repository in Windows Temp. Application source, tests, scripts and
dependency pins are unchanged.

The account lock cannot be repaired by a workflow change. Hosted PASS results are
expected only after the owner resolves it and pushes/re-runs the updated workflow.
No commit, push or remote modification was performed during this investigation.

