"""
adapter.py -- the Aether service side of the federation protocol.

Exposes an ``APIRouter`` mounted by ``app.main`` and a module-level audit
ledger. All ledger *writes* go through ``asyncio.to_thread`` because
python-api runs a single uvicorn worker on one event loop -- a blocking file
write in an async handler would freeze every concurrent request (see
CLAUDE.md's blocking-call trust-boundary note).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

from app.federation import protocol
from app.federation.protocol import AuditLedger, Capability, ServiceManifest

SERVICE_ID = "aether"

# Ledger file lives under the python-api app dir (gitignored). One per process.
_LEDGER_PATH = Path(__file__).resolve().parents[2] / ".federation_ledger.json"
ledger = AuditLedger(service_id=SERVICE_ID, path=_LEDGER_PATH)

router = APIRouter(tags=["federation"])


def build_manifest(base_url: str = "http://gateway:8080") -> ServiceManifest:
    """Advertise Aether's already-public capabilities to the federation hub.

    Only the read/analytics surface is exposed here -- no person entities, no
    write paths -- consistent with this repo's scope guardrails.
    """
    return ServiceManifest(
        service_id=SERVICE_ID,
        display_name="Aether Sovereign OS -- Research Platform",
        kind="service",
        language="python",
        base_url=base_url,
        capabilities=[
            Capability(
                name="research.create-job",
                method="POST",
                path="/research",
                description="Queue a public-records research job (human-reviewed).",
                equivalence="research",
            ),
            Capability(
                name="graph.query",
                method="POST",
                path="/graph/query",
                description="Entity-resolution graph query over public records.",
                equivalence="search",
            ),
            Capability(
                name="analytics.top-entity-types",
                method="GET",
                path="/analytics/top-entity-types",
                description="Aggregated entity-type counts by source.",
                equivalence="search",
            ),
        ],
    )


async def record(action: str, payload: dict[str, Any], actor: str = "") -> None:
    """Append a federation audit event without blocking the event loop."""
    await asyncio.to_thread(ledger.append, action, payload, actor)


@router.get("/federation/health")
async def federation_health() -> dict[str, Any]:
    """Federation liveness for this service + audit chain length."""
    return {
        "status": "ok",
        "service_id": SERVICE_ID,
        "federation_version": protocol.FEDERATION_VERSION,
        "audit_records": len(ledger),
        "secret_secure": not protocol.secret_is_insecure(),
    }


@router.get("/federation/manifest")
async def federation_manifest() -> dict[str, Any]:
    """This service's federation manifest."""
    return build_manifest().to_dict()


@router.get("/federation/audit")
async def federation_audit(limit: int = Query(200, ge=1, le=5000)) -> dict[str, Any]:
    """Export this service's tamper-evident audit chain for the hub.

    Reads in-memory records only -- no disk I/O on this path.
    """
    return {
        "service": SERVICE_ID,
        "head": ledger.head(),
        "records": ledger.records(limit),
    }
