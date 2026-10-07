import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from app.core.exceptions import StoredFileNotFoundError
from app.schemas.file import FileInfoResponse


class FileRepository:
    """One short-lived connection per operation; no shared connection across threads."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    source_crs TEXT NOT NULL,
                    feature_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    stored_filename TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                )
            """)

    def save(self, metadata: FileInfoResponse, stored_filename: str) -> None:
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(metadata.id),
                    metadata.filename,
                    metadata.file_type,
                    metadata.created_at.isoformat(),
                    metadata.crs,
                    metadata.feature_count,
                    metadata.status.value,
                    stored_filename,
                    metadata.model_dump_json(),
                ),
            )

    def get(self, file_id: UUID) -> FileInfoResponse:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT metadata_json FROM files WHERE id = ?", (str(file_id),)
            ).fetchone()
        if row is None:
            raise StoredFileNotFoundError("File not found.")
        return FileInfoResponse.model_validate_json(row[0])
