from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_base_url: str = "http://localhost:8000"
    api_ws_url: str = "ws://localhost:8000"
    worker_token: str = ""
    worker_id: str = "local-worker"
    machine_name: str = "local-machine"
    browser_profiles_dir: str = "profiles"
    screenshots_dir: str = "screenshots"
    headless: bool = False
    xhs_creator_url: str = "https://creator.xiaohongshu.com/publish/publish"
    publish_timeout_seconds: int = 300
    status_callback_retries: int = 5


settings = WorkerSettings()
