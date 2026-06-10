from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket


@dataclass
class WorkerConnection:
    worker_id: str
    websocket: WebSocket
    pending_jobs: list[dict[str, Any]] = field(default_factory=list)


class WorkerHub:
    def __init__(self) -> None:
        self.connections: dict[str, WorkerConnection] = {}
        self.browser_sessions: dict[str, WebSocket] = {}

    async def connect_worker(self, worker_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections[worker_id] = WorkerConnection(worker_id=worker_id, websocket=websocket)

    def disconnect_worker(self, worker_id: str) -> None:
        self.connections.pop(worker_id, None)

    async def connect_browser_session(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.browser_sessions[session_id] = websocket

    def disconnect_browser_session(self, session_id: str) -> None:
        self.browser_sessions.pop(session_id, None)

    async def send_job(self, worker_id: str, job: dict[str, Any]) -> bool:
        connection = self.connections.get(worker_id)
        if not connection:
            return False
        await connection.websocket.send_json({"type": "publish_job", "job": job})
        return True

    async def send_browser_event(
        self, worker_id: str, session_id: str, job_id: str, event: dict[str, Any]
    ) -> bool:
        connection = self.connections.get(worker_id)
        if not connection:
            return False
        await connection.websocket.send_json(
            {"type": "browser_event", "session_id": session_id, "job_id": job_id, "event": event}
        )
        return True

    async def forward_browser_frame(self, session_id: str, frame: dict[str, Any]) -> bool:
        websocket = self.browser_sessions.get(session_id)
        if not websocket:
            return False
        await websocket.send_json(frame)
        return True


worker_hub = WorkerHub()
