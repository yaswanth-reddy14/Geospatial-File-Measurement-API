FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production
WORKDIR /app

# Binary geospatial wheels bundle GDAL/GEOS/PROJ; fail rather than compile an accidental stack.
COPY requirements.txt ./
RUN pip install --only-binary=:all: -r requirements.txt \
    && groupadd --gid 10001 api \
    && useradd --uid 10001 --gid api --no-create-home api \
    && mkdir -p /app/data/uploads /app/data/processed \
    && chown -R api:api /app/data

COPY app ./app
USER api
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
