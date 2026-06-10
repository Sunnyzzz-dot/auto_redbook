from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import encrypt_secret
from app.models import ModelKey, User, XhsAccount
from app.schemas.settings import (
    ModelKeyCreate,
    ModelKeyResponse,
    XhsAccountCreate,
    XhsAccountResponse,
)

router = APIRouter(tags=["settings"])


@router.post("/model-keys", response_model=ModelKeyResponse)
async def create_model_key(
    payload: ModelKeyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ModelKeyResponse:
    key = ModelKey(
        user_id=user.id,
        provider=payload.provider,
        encrypted_api_key=encrypt_secret(payload.api_key),
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return ModelKeyResponse(id=key.id, provider=key.provider, status=key.status)


@router.get("/model-keys", response_model=list[ModelKeyResponse])
async def list_model_keys(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[ModelKeyResponse]:
    result = await db.execute(select(ModelKey).where(ModelKey.user_id == user.id))
    return [
        ModelKeyResponse(id=item.id, provider=item.provider, status=item.status)
        for item in result.scalars()
    ]


@router.post("/xhs-accounts", response_model=XhsAccountResponse)
async def create_xhs_account(
    payload: XhsAccountCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> XhsAccountResponse:
    account = XhsAccount(
        user_id=user.id,
        display_name=payload.display_name,
        bound_worker_id=payload.bound_worker_id,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return XhsAccountResponse(
        id=account.id,
        display_name=account.display_name,
        bound_worker_id=account.bound_worker_id,
        browser_profile_id=account.browser_profile_id,
        login_status=account.login_status,
    )


@router.get("/xhs-accounts", response_model=list[XhsAccountResponse])
async def list_xhs_accounts(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[XhsAccountResponse]:
    result = await db.execute(select(XhsAccount).where(XhsAccount.user_id == user.id))
    return [
        XhsAccountResponse(
            id=item.id,
            display_name=item.display_name,
            bound_worker_id=item.bound_worker_id,
            browser_profile_id=item.browser_profile_id,
            login_status=item.login_status,
        )
        for item in result.scalars()
    ]

