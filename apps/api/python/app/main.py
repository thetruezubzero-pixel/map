from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.config import get_settings
from app.routers import health, research

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pool is created lazily on first use (see db.get_pool) so the service
    # can boot and serve /health even if Postgres isn't reachable yet.
    yield
    await db.close_pool()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Aether Sovereign OS -- Research Orchestration",
        version="0.2.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
    )

    app.include_router(health.router)
    app.include_router(research.router)

    return app


app = create_app()
