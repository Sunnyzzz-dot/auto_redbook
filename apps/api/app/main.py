from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import agent, auth, drafts, publish, settings
from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.database import Base, engine
from app.models import User, entities  # noqa: F401 - ensure models are registered.


def create_app() -> FastAPI:
    settings_obj = get_settings()
    app = FastAPI(title="Red Book Agent API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings_obj.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router, prefix="/api")
    app.include_router(settings.router, prefix="/api")
    app.include_router(agent.router, prefix="/api")
    app.include_router(drafts.router, prefix="/api")
    app.include_router(publish.router, prefix="/api")

    upload_dir = Path(settings_obj.local_upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=str(upload_dir)), name="uploads")

    @app.on_event("startup")
    async def startup() -> None:
        if settings_obj.app_env == "local":
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/me")
    async def me_alias(user: User = Depends(get_current_user)) -> dict[str, str]:
        return {"id": user.id, "email": user.email, "role": user.role}

    return app


app = create_app()
