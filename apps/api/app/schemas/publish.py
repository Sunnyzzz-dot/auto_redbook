from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class PublishJobCreate(BaseModel):
    draft_id: str
    account_id: str
    publish_mode: Literal["manual_approve", "auto_publish"] = "manual_approve"


class PublishJobResponse(BaseModel):
    id: str
    draft_id: str
    account_id: str
    publish_mode: str
    status: str
    result_url: str | None
    screenshot_url: str | None
    failure_reason: str | None
    worker_id: str | None
    created_at: datetime
    updated_at: datetime


class BrowserSessionResponse(BaseModel):
    id: str
    job_id: str
    status: str
    expires_at: datetime
