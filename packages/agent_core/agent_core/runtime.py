from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from agent_core.schemas import AgentEvent, AgentStep, StepStatus, ToolCall
from agent_core.tools import ToolRegistry


EventSink = Callable[[AgentEvent], Awaitable[None]]


class AgentRuntime:
    """Small ReAct-style executor that records thought/action/observation steps."""

    def __init__(self, tools: ToolRegistry, event_sink: EventSink | None = None) -> None:
        self.tools = tools
        self.event_sink = event_sink

    async def run_plan(self, run_id: UUID, plan: Iterable[tuple[str, str, ToolCall]]) -> list[AgentStep]:
        steps: list[AgentStep] = []
        memory: dict[str, Any] = {}

        for step_name, thought_summary, call in plan:
            payload = {**call.input, "memory": memory}
            step = AgentStep(
                run_id=run_id,
                step=step_name,
                thought_summary=thought_summary,
                action=call.name,
                action_input=payload,
                status=StepStatus.RUNNING,
            )
            await self._emit("step_started", step)

            result = await self.tools.call(call.name, payload)
            step.observation = result.output
            step.completed_at = datetime.now(UTC)

            if result.is_error:
                step.status = StepStatus.FAILED
                step.error = result.error
                await self._emit("step_failed", step)
                steps.append(step)
                break

            step.status = StepStatus.SUCCEEDED
            memory[step_name] = result.output
            await self._emit("step_succeeded", step)
            steps.append(step)

        return steps

    async def _emit(self, event_type: str, step: AgentStep) -> None:
        if self.event_sink is not None:
            await self.event_sink(AgentEvent(run_id=step.run_id, step=step, type=event_type))

