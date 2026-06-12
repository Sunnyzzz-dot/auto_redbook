from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import AsyncSessionLocal, get_db
from app.models import AgentRun, DraftNote, User
from app.schemas.agent import AgentRunCreate, AgentRunResponse, DraftUpdateRequest, RegenerateRequest
from app.services.agent_service import AgentService

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/runs", response_model=AgentRunResponse)
async def create_run(
    payload: AgentRunCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentRunResponse:
    service = AgentService(db)
    run = await service.create_run_record(
        user.id,
        payload.instruction,
        payload.model_dump(exclude={"instruction"}),
    )
    background_tasks.add_task(_execute_run_background, user.id, run.id)
    return serialize_run(run)


@router.get("/runs/{run_id}", response_model=AgentRunResponse)
async def get_run(
    run_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentRunResponse:
    return serialize_run(await AgentService(db).get_run(user.id, run_id))


@router.post("/runs/{run_id}/regenerate", response_model=AgentRunResponse)
async def regenerate(
    run_id: str,
    payload: RegenerateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentRunResponse:
    run = await AgentService(db).regenerate(
        user.id,
        run_id,
        payload.target,
        payload.image_count,
        payload.instruction_override,
    )
    return serialize_run(run)


def serialize_run(run: AgentRun) -> AgentRunResponse:
    return AgentRunResponse.model_validate(
        {
            "id": run.id,
            "instruction": run.instruction,
            "status": run.status,
            "config": run.config,
            "failure_reason": run.failure_reason,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
            "steps": [
                {
                    "id": step.id,
                    "step": step.step,
                    "thought_summary": step.thought_summary,
                    "action": step.action,
                    "action_input": step.action_input,
                    "observation": step.observation,
                    "status": step.status,
                    "error": step.error,
                    "created_at": step.created_at,
                    "completed_at": step.completed_at,
                }
                for step in run.steps
            ],
            "draft": serialize_draft(run.draft) if run.draft else None,
        }
    )


async def _execute_run_background(user_id: str, run_id: str) -> None:
    async with AsyncSessionLocal() as db:
        try:
            await AgentService(db).execute_existing_run(user_id, run_id)
        except Exception as exc:  # noqa: BLE001 - surface background model failures to the UI.
            run = await db.get(AgentRun, run_id)
            if run:
                run.status = "failed"
                run.failure_reason = str(exc)
                await db.commit()


def serialize_draft(draft: DraftNote) -> dict:
    return {
        "id": draft.id,
        "title_candidates": draft.title_candidates,
        "selected_title": draft.selected_title,
        "body": draft.body,
        "hashtags": draft.hashtags,
        "style": draft.style,
        "target_audience": draft.target_audience,
        "safety_report": draft.safety_report,
        "images": [
            {
                "id": image.id,
                "image_url": f"/api/publish-assets/{image.id}?v={int(image.created_at.timestamp())}",
                "prompt": image.prompt,
                "seed": image.seed,
                "ratio": image.ratio,
                "sort_order": image.sort_order,
                "is_selected": image.is_selected,
            }
            for image in draft.images
        ],
    }
