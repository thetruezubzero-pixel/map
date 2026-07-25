"""
hub_client.py -- outbound link from this service to the federation hub.

Turns the service from a *pull-only* federated member (it exposes an audit
chain the hub can read) into an *active* one: on startup it registers its
manifest with the hub, and it can push activity events onto the hub's event
bus as they happen.

Everything here is **opt-in** via the ``FEDERATION_HUB_URL`` env var and
**fails soft**: if the hub URL is unset or the hub is unreachable, every call
is a safe no-op that returns ``False`` instead of raising, so this service
never depends on the hub being up. All calls are async (httpx) -- no blocking
I/O in the event loop, per this repo's trust-boundary rules.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx


def hub_url() -> str:
    """The configured hub base URL (trailing slash stripped), or ""."""
    return os.environ.get("FEDERATION_HUB_URL", "").strip().rstrip("/")


def enabled() -> bool:
    """True when a hub URL is configured; otherwise every call no-ops."""
    return bool(hub_url())


async def _post(
    path: str,
    *,
    params: Optional[dict[str, Any]] = None,
    json: Optional[dict[str, Any]] = None,
    timeout: float = 3.0,
    transport: Optional[httpx.BaseTransport] = None,
) -> bool:
    """POST to the hub, swallowing every error into a ``False`` result."""
    if not enabled():
        return False
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            resp = await client.post(hub_url() + path, params=params, json=json)
            return resp.status_code < 400
    except Exception:
        return False


async def register(
    manifest: dict[str, Any], *, transport: Optional[httpx.BaseTransport] = None
) -> bool:
    """Register this service's manifest with the hub."""
    return await _post("/federation/register", json=manifest, transport=transport)


async def emit(
    topic: str,
    event_type: str,
    payload: dict[str, Any],
    source: str,
    *,
    transport: Optional[httpx.BaseTransport] = None,
) -> bool:
    """Push one activity event onto the hub's event bus."""
    return await _post(
        "/federation/bus/publish",
        params={"topic": topic, "event_type": event_type, "source": source},
        json=payload,
        transport=transport,
    )
