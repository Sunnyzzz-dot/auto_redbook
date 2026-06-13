from __future__ import annotations

import asyncio
import json
from urllib.parse import urlencode

import httpx
import websockets

from worker.config import settings
from worker.publisher import PublishResult, XiaohongshuPublisher, screenshot_to_data_url


def _log(message: str) -> None:
    print(message, flush=True)


async def run_worker() -> None:
    query = {"worker_id": settings.worker_id, "machine_name": settings.machine_name}
    if settings.worker_token:
        query["token"] = settings.worker_token
    uri = f"{settings.api_ws_url}/api/workers/connect?{urlencode(query)}"
    publisher = XiaohongshuPublisher()

    while True:
        try:
            _log(f"worker connecting to {uri}")
            async with websockets.connect(uri, ping_interval=20, ping_timeout=20) as websocket:
                await websocket.send(json.dumps({"type": "hello", "worker_id": settings.worker_id}))
                _log("worker connected")
                async for raw in websocket:
                    message = json.loads(raw)
                    if message.get("type") != "publish_job":
                        if message.get("type") == "browser_event":
                            frame = await publisher.handle_browser_event(
                                message["job_id"], message.get("event", {})
                            )
                            if frame.get("type") in {"browser_frame", "job_status"}:
                                frame["session_id"] = message.get("session_id")
                            if frame.get("type") == "job_status":
                                frame["worker_id"] = settings.worker_id
                                await _send_job_status(websocket, frame)
                            else:
                                await websocket.send(json.dumps(frame))
                        continue
                    job = message["job"]
                    job_id = job.get("job_id", "unknown-job")
                    _log(f"publish_job {job_id}: received")
                    try:
                        result = await asyncio.wait_for(
                            publisher.publish(job),
                            timeout=settings.publish_timeout_seconds,
                        )
                    except TimeoutError:
                        _log(f"publish_job {job_id}: timeout")
                        result = PublishResult(status="failed", failure_reason="publish_timeout")
                    except Exception as exc:  # noqa: BLE001 - report job failures to the API.
                        _log(f"publish_job {job_id}: failed: {exc}")
                        result = PublishResult(status="failed", failure_reason=str(exc))
                    status_message = {
                        "type": "job_status",
                        "job_id": job_id,
                        "worker_id": settings.worker_id,
                        "status": result.status,
                        "failure_reason": result.failure_reason,
                        "result_url": result.result_url,
                        "screenshot_url": screenshot_to_data_url(result.screenshot_path),
                    }
                    await _send_job_status(websocket, status_message)
                    _log(f"publish_job {job_id}: status_reported {result.status}")
        except Exception as exc:  # noqa: BLE001 - worker should reconnect forever.
            _log(f"worker reconnecting after error: {exc}")
            await asyncio.sleep(5)


async def _send_job_status(websocket, message: dict) -> None:
    try:
        await websocket.send(json.dumps(message))
        _log(f"publish_job {message.get('job_id')}: websocket_status_ok")
    except Exception as exc:  # noqa: BLE001 - fall back to the HTTP callback.
        _log(f"publish_job {message.get('job_id')}: websocket_status_failed: {exc}")
    await _callback_job_status(message)


async def _callback_job_status(message: dict) -> None:
    job_id = message.get("job_id")
    if not job_id:
        return

    url = f"{settings.api_base_url.rstrip('/')}/api/workers/jobs/{job_id}/status"
    headers = {}
    if settings.worker_token:
        headers["Authorization"] = f"Bearer {settings.worker_token}"
    payload = {
        "worker_id": settings.worker_id,
        "status": message.get("status"),
        "failure_reason": message.get("failure_reason"),
        "result_url": message.get("result_url"),
        "screenshot_url": message.get("screenshot_url"),
        "session_id": message.get("session_id"),
    }
    for attempt in range(1, settings.status_callback_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
            _log(f"publish_job {job_id}: http_status_callback_ok")
            return
        except Exception as exc:  # noqa: BLE001 - retry transient API outages.
            _log(f"publish_job {job_id}: http_status_callback_failed attempt={attempt}: {exc}")
            await asyncio.sleep(min(10, attempt * 2))


if __name__ == "__main__":
    asyncio.run(run_worker())
