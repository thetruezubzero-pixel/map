from __future__ import annotations

from typing import Any
from uuid import UUID

from app import db


class Agent:
    name: str = "base_agent"

    async def audit(self, job_id: UUID | None, action: str, detail: dict[str, Any]) -> None:
        await db.write_audit_log(job_id, self.name, action, detail)
