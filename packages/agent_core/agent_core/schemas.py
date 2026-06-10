from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class ToolCall(BaseModel):
    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    name: str
    output: dict[str, Any] = Field(default_factory=dict)
    is_error: bool = False
    error: str | None = None


class AgentStep(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    step: str
    thought_summary: str
    action: str
    action_input: dict[str, Any] = Field(default_factory=dict)
    observation: dict[str, Any] = Field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class AgentEvent(BaseModel):
    run_id: UUID
    step: AgentStep
    type: str


ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

