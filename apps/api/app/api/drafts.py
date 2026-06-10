from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.agent import serialize_draft
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import DraftNote, User
from app.schemas.agent import DraftResponse, DraftUpdateRequest

router = APIRouter(prefix="/drafts", tags=["drafts"])


@router.patch("/{draft_id}", response_model=DraftResponse)
async def update_draft(
    draft_id: str,
    payload: DraftUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DraftResponse:
    result = await db.execute(
        select(DraftNote)
        .where(DraftNote.id == draft_id, DraftNote.user_id == user.id)
        .options(selectinload(DraftNote.images))
    )
    draft = result.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    if payload.selected_title is not None:
        draft.selected_title = payload.selected_title[:20]
    if payload.body is not None:
        draft.body = payload.body
    if payload.hashtags is not None:
        draft.hashtags = payload.hashtags
    if payload.image_order is not None:
        order = {image_id: index for index, image_id in enumerate(payload.image_order)}
        for image in draft.images:
            if image.id in order:
                image.sort_order = order[image.id]

    await db.commit()
    await db.refresh(draft)
    draft.images.sort(key=lambda item: item.sort_order)
    return DraftResponse.model_validate(serialize_draft(draft))
