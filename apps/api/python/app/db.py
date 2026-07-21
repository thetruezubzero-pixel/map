from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg

from app.config import get_settings

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=10)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def create_research_job(query: str, requested_by: str | None) -> asyncpg.Record:
    pool = await get_pool()
    return await pool.fetchrow(
        """
        INSERT INTO research_jobs (query, requested_by, status)
        VALUES ($1, $2, 'queued')
        RETURNING id, query, requested_by, status, result, created_at, updated_at
        """,
        query,
        requested_by,
    )


async def get_research_job(job_id: UUID) -> asyncpg.Record | None:
    pool = await get_pool()
    return await pool.fetchrow(
        """
        SELECT id, query, requested_by, status, result, created_at, updated_at
        FROM research_jobs WHERE id = $1
        """,
        job_id,
    )


async def update_research_job(
    job_id: UUID, status: str, result: dict[str, Any] | None = None
) -> None:
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE research_jobs
        SET status = $2, result = $3, updated_at = now()
        WHERE id = $1
        """,
        job_id,
        status,
        json.dumps(result) if result is not None else None,
    )


async def write_audit_log(job_id: UUID | None, agent_name: str, action: str, detail: dict[str, Any]) -> None:
    """Append-only audit trail; agent_audit_log rejects UPDATE/DELETE at the DB level."""
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO agent_audit_log (job_id, agent_name, action, detail)
        VALUES ($1, $2, $3, $4)
        """,
        job_id,
        agent_name,
        action,
        json.dumps(detail),
    )
