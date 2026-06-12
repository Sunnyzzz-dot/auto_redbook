from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.agent import serialize_draft
from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, get_db
from app.core.security import decode_access_token
from app.models import BrowserSession, DraftImage, DraftNote, PublishJob, User, Worker, XhsAccount
from app.schemas.publish import BrowserSessionResponse, PublishJobCreate, PublishJobResponse
from app.services.storage import ObjectStorage
from app.services.worker_hub import worker_hub

router = APIRouter(tags=["publish"])


@router.post("/publish-jobs", response_model=PublishJobResponse)
async def create_publish_job(
    payload: PublishJobCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PublishJobResponse:
    draft = await db.scalar(
        select(DraftNote)
        .where(DraftNote.id == payload.draft_id, DraftNote.user_id == user.id)
        .options(selectinload(DraftNote.images))
    )
    account = await db.scalar(
        select(XhsAccount).where(XhsAccount.id == payload.account_id, XhsAccount.user_id == user.id)
    )
    if not draft or not account:
        raise HTTPException(status_code=404, detail="Draft or account not found")
    job = PublishJob(
        draft_id=draft.id,
        account_id=account.id,
        user_id=user.id,
        publish_mode=payload.publish_mode,
        worker_id=account.bound_worker_id,
        status="queued",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    if account.bound_worker_id:
        draft_payload = serialize_draft(draft)
        settings = get_settings()
        base_url = (settings.worker_asset_base_url or str(request.base_url)).rstrip("/")
        for image in draft_payload["images"]:
            image["image_url"] = f"{base_url}/api/publish-assets/{image['id']}"
        sent = await worker_hub.send_job(
            account.bound_worker_id,
            {
                "job_id": job.id,
                "draft_id": draft.id,
                "account_id": account.id,
                "publish_mode": job.publish_mode,
                "draft": draft_payload,
            },
        )
        if sent:
            job.status = "sent_to_worker"
            await db.commit()
            await db.refresh(job)

    return serialize_job(job)


@router.get("/publish-assets/{image_id}")
async def get_publish_asset(image_id: str, db: AsyncSession = Depends(get_db)) -> Response:
    image = await db.get(DraftImage, image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Asset not found")
    try:
        data, content_type = ObjectStorage().get_bytes_for_url(image.image_url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Asset storage read failed") from exc
    return Response(content=data, media_type=content_type, headers={"Cache-Control": "no-store"})


@router.get("/publish-jobs/{job_id}", response_model=PublishJobResponse)
async def get_publish_job(
    job_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PublishJobResponse:
    job = await db.scalar(select(PublishJob).where(PublishJob.id == job_id, PublishJob.user_id == user.id))
    if not job:
        raise HTTPException(status_code=404, detail="Publish job not found")
    return serialize_job(job)


@router.post("/publish-jobs/{job_id}/approve", response_model=PublishJobResponse)
async def approve_publish_job(
    job_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PublishJobResponse:
    job = await db.scalar(select(PublishJob).where(PublishJob.id == job_id, PublishJob.user_id == user.id))
    if not job:
        raise HTTPException(status_code=404, detail="Publish job not found")
    job.status = "approved"
    await db.commit()
    await db.refresh(job)
    if job.worker_id:
        await worker_hub.send_job(job.worker_id, {"type": "approval", "job_id": job.id})
    return serialize_job(job)


@router.get("/publish-jobs/{job_id}/browser-session", response_model=BrowserSessionResponse)
async def get_browser_session(
    job_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BrowserSessionResponse:
    job = await db.scalar(select(PublishJob).where(PublishJob.id == job_id, PublishJob.user_id == user.id))
    if not job:
        raise HTTPException(status_code=404, detail="Publish job not found")
    session = await db.scalar(
        select(BrowserSession)
        .where(BrowserSession.job_id == job.id, BrowserSession.status == "active")
        .order_by(BrowserSession.created_at.desc())
    )
    if not session:
        raise HTTPException(status_code=404, detail="Browser session not found")
    return BrowserSessionResponse(
        id=session.id,
        job_id=session.job_id,
        status=session.status,
        expires_at=session.expires_at,
    )


@router.websocket("/workers/connect")
async def workers_connect(websocket: WebSocket) -> None:
    worker_id = websocket.query_params.get("worker_id", "local-worker")
    machine_name = websocket.query_params.get("machine_name", worker_id)
    expected_token = get_settings().worker_token
    if expected_token and websocket.query_params.get("token") != expected_token:
        await websocket.close(code=1008)
        return
    await worker_hub.connect_worker(worker_id, websocket)
    async with AsyncSessionLocal() as db:
        worker = await db.get(Worker, worker_id)
        if not worker:
            worker = Worker(id=worker_id, machine_name=machine_name, status="online")
            db.add(worker)
        else:
            worker.status = "online"
        await db.commit()
    try:
        while True:
            message = await websocket.receive_json()
            await handle_worker_message(worker_id, message)
    except WebSocketDisconnect:
        worker_hub.disconnect_worker(worker_id)
        async with AsyncSessionLocal() as db:
            worker = await db.get(Worker, worker_id)
            if worker:
                worker.status = "offline"
                await db.commit()


async def handle_worker_message(worker_id: str, message: dict) -> None:
    if message.get("type") == "browser_frame" and message.get("session_id"):
        await worker_hub.forward_browser_frame(message["session_id"], message)
        return

    session_id = message.get("session_id")
    async with AsyncSessionLocal() as db:
        if message.get("type") == "job_status":
            job = await db.get(PublishJob, message.get("job_id"))
            if job:
                job.worker_id = worker_id
                job.status = message.get("status", job.status)
                job.failure_reason = message.get("failure_reason")
                job.result_url = message.get("result_url")
                job.screenshot_url = message.get("screenshot_url")
                if job.status in {"requires_human_intervention", "awaiting_manual_approval"}:
                    session = await db.scalar(
                        select(BrowserSession).where(
                            BrowserSession.job_id == job.id,
                            BrowserSession.status == "active",
                        )
                    )
                    if not session:
                        db.add(BrowserSession(job_id=job.id))
                elif job.status in {"published", "failed"}:
                    sessions = await db.scalars(
                        select(BrowserSession).where(
                            BrowserSession.job_id == job.id,
                            BrowserSession.status == "active",
                        )
                    )
                    for session in sessions:
                        session.status = "closed"
                await db.commit()
                if session_id:
                    await worker_hub.forward_browser_frame(session_id, message)


@router.websocket("/browser-sessions/{session_id}")
async def browser_session(websocket: WebSocket, session_id: str) -> None:
    token = websocket.query_params.get("token", "")
    try:
        user_id = decode_access_token(token)
    except ValueError:
        await websocket.close(code=1008)
        return
    async with AsyncSessionLocal() as db:
        session = await db.get(BrowserSession, session_id)
        if not session or session.status != "active":
            await websocket.close(code=1008)
            return
        job = await db.get(PublishJob, session.job_id)
        if not job or job.user_id != user_id:
            await websocket.close(code=1008)
            return

    await worker_hub.connect_browser_session(session_id, websocket)
    await websocket.send_json(
        {
            "type": "session_ready",
            "session_id": session_id,
            "message": "Remote browser bridge is ready. Worker-side streaming is enabled in apps/worker.",
        }
    )
    try:
        while True:
            event = await websocket.receive_json()
            async with AsyncSessionLocal() as db:
                session = await db.get(BrowserSession, session_id)
                if not session:
                    await websocket.send_json({"type": "error", "error": "session_not_found"})
                    continue
                job = await db.get(PublishJob, session.job_id)
                if not job or not job.worker_id:
                    await websocket.send_json({"type": "error", "error": "worker_not_found"})
                    continue
                sent = await worker_hub.send_browser_event(
                    job.worker_id, session_id, job.id, event
                )
                if not sent:
                    await websocket.send_json({"type": "error", "error": "worker_offline"})
    except WebSocketDisconnect:
        worker_hub.disconnect_browser_session(session_id)
        return


def serialize_job(job: PublishJob) -> PublishJobResponse:
    return PublishJobResponse(
        id=job.id,
        draft_id=job.draft_id,
        account_id=job.account_id,
        publish_mode=job.publish_mode,
        status=job.status,
        result_url=job.result_url,
        screenshot_url=job.screenshot_url,
        failure_reason=job.failure_reason,
        worker_id=job.worker_id,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
