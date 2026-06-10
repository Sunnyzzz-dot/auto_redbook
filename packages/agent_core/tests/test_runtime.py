from uuid import uuid4

import pytest

from agent_core.runtime import AgentRuntime
from agent_core.schemas import StepStatus, ToolCall
from agent_core.tools import Tool, ToolRegistry


@pytest.mark.asyncio
async def test_runtime_records_react_steps() -> None:
    registry = ToolRegistry()

    async def handler(payload: dict) -> dict:
        return {"ok": True, "memory_keys": list(payload["memory"].keys())}

    registry.register(Tool("demo.tool", "demo", handler))
    runtime = AgentRuntime(registry)

    steps = await runtime.run_plan(
        uuid4(),
        [("first", "call a tool", ToolCall(name="demo.tool", input={"value": 1}))],
    )

    assert len(steps) == 1
    assert steps[0].status == StepStatus.SUCCEEDED
    assert steps[0].observation["ok"] is True


@pytest.mark.asyncio
async def test_runtime_stops_on_tool_error() -> None:
    registry = ToolRegistry()

    async def boom(_: dict) -> dict:
        raise RuntimeError("bad")

    registry.register(Tool("bad.tool", "bad", boom))
    runtime = AgentRuntime(registry)

    steps = await runtime.run_plan(
        uuid4(),
        [("first", "call a bad tool", ToolCall(name="bad.tool"))],
    )

    assert steps[0].status == StepStatus.FAILED
    assert steps[0].error == "bad"
