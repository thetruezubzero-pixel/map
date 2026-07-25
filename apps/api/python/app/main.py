from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.config import get_settings
from app.federation.adapter import router as federation_router
from app.routers import agent_swarm, analytics, architect, chat, graph, health, research

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pool is created lazily on first use (see db.get_pool) so the service
    # can boot and serve /health even if Postgres isn't reachable yet.
    # Announce this service to the federation hub if FEDERATION_HUB_URL is set
    # (no-op otherwise; fails soft so hub downtime never blocks startup).
    from app.federation.adapter import announce

    try:
        await announce()
    except Exception:  # never let federation wiring break boot
        logging.getLogger(__name__).warning("federation announce failed", exc_info=True)
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
    app.include_router(graph.router)
    app.include_router(analytics.router)
    app.include_router(agent_swarm.router)
    app.include_router(architect.router)
    app.include_router(chat.router)
    # Federation adapter (/federation/*): read-only self-description + a
    # tamper-evident audit chain the Neural Swarm hub verifies. No new write
    # path or person-entity surface -- see app/federation/__init__.py.
    app.include_router(federation_router)

    return app


app = create_app()
