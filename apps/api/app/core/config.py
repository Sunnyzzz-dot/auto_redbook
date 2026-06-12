from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    app_secret_key: str = Field(default="change-me-to-a-32-byte-secret")
    database_url: str = "postgresql+asyncpg://redbook:redbook@localhost:5432/redbook_agent"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_access_key_id: str | None = "minioadmin"
    s3_secret_access_key: str | None = "minioadmin"
    s3_bucket: str = "redbook-agent"
    s3_public_base_url: str | None = "http://localhost:9000/redbook-agent"
    local_upload_dir: str = "uploads"
    public_upload_base_url: str = "http://localhost:8000/uploads"
    cors_origins: str = (
        "http://localhost:5173,"
        "http://127.0.0.1:5173,"
        "http://localhost:5174,"
        "http://127.0.0.1:5174"
    )
    worker_token: str = ""
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    doubao_text_model: str = "doubao-seed-2-0-lite-260215"
    doubao_image_model: str = "doubao-seedream-5-0-260128"
    doubao_image_size: str = "2K"
    allow_mock_models: bool = True
    jwt_expires_minutes: int = 10080

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
