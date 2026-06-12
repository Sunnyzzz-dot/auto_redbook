from __future__ import annotations

import asyncio
import json
from urllib.parse import urlencode

import websockets

from worker.config import settings
from worker.publisher import PublishResult, XiaohongshuPublisher, screenshot_to_data_url


async def run_worker() -> None:
    query = {"worker_id": settings.worker_id, "machine_name": settings.machine_name}
    if settings.worker_token:
        query["token"] = settings.worker_token
    uri = f"{settings.api_ws_url}/api/workers/connect?{urlencode(query)}"
    publisher = XiaohongshuPublisher()
    print(f"worker connecting to {uri}")

    while True:
        try:
            async with websockets.connect(uri, ping_interval=20, ping_timeout=20) as websocket:
                await websocket.send(json.dumps({"type": "hello", "worker_id": settings.worker_id}))
                async for raw in websocket:
                    message = json.loads(raw)
                    if message.get("type") != "publish_job":
                        if message.get("type") == "browser_event":
                            frame = await publisher.handle_browser_event(
                                message["job_id"], message.get("event", {})
                            )
                            if frame.get("type") in {"browser_frame", "job_status"}:
                                frame["session_id"] = message.get("session_id")
                            await websocket.send(json.dumps(frame))
                        continue
                    job = message["job"]
                    try:
                        result = await publisher.publish(job)
                    except Exception as exc:  # noqa: BLE001 - report job failures to the API.
                        result = PublishResult(status="failed", failure_reason=str(exc))
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "job_status",
                                "job_id": job["job_id"],
                                "status": result.status,
                                "failure_reason": result.failure_reason,
                                "result_url": result.result_url,
                                "screenshot_url": screenshot_to_data_url(result.screenshot_path),
                            }
                        )
                    )
        except Exception as exc:  # noqa: BLE001 - worker should reconnect forever.
            print(f"worker reconnecting after error: {exc}")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(run_worker())
