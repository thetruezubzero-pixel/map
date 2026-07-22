from __future__ import annotations

from fastapi import APIRouter

from app import db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    db_ok = True
    try:
        pool = await db.get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
    except Exception:
        db_ok = False

    return {"status": "ok" if db_ok else "degraded", "service": "aether-python-api", "db": db_ok}
