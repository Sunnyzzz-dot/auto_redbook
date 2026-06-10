from __future__ import annotations

from pydantic import BaseModel, Field


class ModelKeyCreate(BaseModel):
    api_key: str = Field(min_length=8)
    provider: str = "volcengine_ark"


class ModelKeyResponse(BaseModel):
    id: str
    provider: str
    status: str


class XhsAccountCreate(BaseModel):
    display_name: str
    bound_worker_id: str | None = None


class XhsAccountResponse(BaseModel):
    id: str
    display_name: str
    bound_worker_id: str | None
    browser_profile_id: str
    login_status: str

