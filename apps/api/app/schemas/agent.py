from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentRunCreate(BaseModel):
    instruction: str = Field(min_length=2, max_length=2000)
    image_count: int = Field(default=3, ge=1, le=9)
    image_ratio: str = "3:4"
    style_hint: str | None = None
    target_audience_hint: str | None = None
    mode: Literal["standard", "advanced"] = "standard"


class AgentStepResponse(BaseModel):
    id: str
    step: str
    thought_summary: str
    action: str
    action_input: dict[str, Any]
    observation: dict[str, Any]
    status: str
    error: str | None
    created_at: datetime
    completed_at: datetime | None


class DraftImageResponse(BaseModel):
    id: str
    image_url: str
    prompt: str
    seed: int | None
    ratio: str
    sort_order: int
    is_selected: bool


class DraftResponse(BaseModel):
    id: str
    title_candidates: list[str]
    selected_title: str
    body: str
    hashtags: list[str]
    style: str
    target_audience: str
    safety_report: dict[str, Any]
    images: list[DraftImageResponse]


class AgentRunResponse(BaseModel):
    id: str
    instruction: str
    status: str
    config: dict[str, Any]
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime
    steps: list[AgentStepResponse]
    draft: DraftResponse | None = None


class RegenerateRequest(BaseModel):
    target: Literal["titles", "body", "hashtags", "images", "safety"]
    image_count: int | None = Field(default=None, ge=1, le=9)
    instruction_override: str | None = None


class DraftUpdateRequest(BaseModel):
    selected_title: str | None = None
    body: str | None = None
    hashtags: list[str] | None = None
    image_order: list[str] | None = None

