from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    upload_dir: Path = Path("data/uploads")
    processed_dir: Path = Path("data/processed")
    database_url: str = "sqlite:///./data/app.db"
    max_upload_size_mb: int = Field(default=50, ge=1)
    max_archive_size_mb: int = Field(default=200, ge=1)
    max_archive_members: int = Field(default=256, ge=1)
    max_compression_ratio: float = Field(default=100, ge=1)
    max_features: int = Field(default=10000, ge=1)
    max_coordinates: int = Field(default=1000000, ge=1)

    @model_validator(mode="after")
    def validate_storage(self) -> "Settings":
        if not self.database_url.startswith("sqlite:///"):
            raise ValueError("Only file-backed SQLite URLs are supported.")
        if self.database_url.removeprefix("sqlite:///") in {"", ":memory:"}:
            raise ValueError("DATABASE_URL must name a database file.")
        return self

    @property
    def database_path(self) -> Path:
        return Path(self.database_url.removeprefix("sqlite:///"))

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def max_archive_bytes(self) -> int:
        return self.max_archive_size_mb * 1024 * 1024
