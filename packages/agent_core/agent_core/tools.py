from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_core.schemas import ToolHandler, ToolResult


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    handler: ToolHandler


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}") from exc

    def list(self) -> list[Tool]:
        return list(self._tools.values())

    async def call(self, name: str, payload: dict[str, Any]) -> ToolResult:
        tool = self.get(name)
        try:
            output = await tool.handler(payload)
            return ToolResult(name=name, output=output)
        except Exception as exc:  # noqa: BLE001 - tool errors must be captured in traces.
            return ToolResult(name=name, is_error=True, error=str(exc))

