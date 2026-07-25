"""
federation -- Aether's adapter for the cross-repository federation.

This makes the Aether python-api a *federated service* alongside three sibling
repositories (jfjf/Neural-Swarm, Jit-, Mom-) **without merging any codebase**.
It self-describes its capabilities in a manifest, keeps a tamper-evident audit
ledger of federation activity, and exposes the ``/federation/*`` surface the
Neural Swarm hub uses to register, health-check, and forensically verify this
service.

Scope notes specific to this repo (see CLAUDE.md):
  - This adapter is read-only + self-describing. It advertises only the
    already-public research/graph/analytics capabilities; it adds no new
    person-entity surface, no write path, and no new consumer of python-api's
    internals.
  - The "blockchain" here is a LOCAL hash-chained audit ledger. It is NOT
    wired to IPFS/real-chain infrastructure -- doing so is forbidden without a
    written ROADMAP.md scope decision because it spends real money. The local
    chain gives the same tamper-evidence with none of that risk.
  - python-api runs a single uvicorn worker, so any ledger *write* must go
    through ``asyncio.to_thread`` (see ``adapter.record``); the read/verify
    endpoints only touch in-memory state.
"""

from __future__ import annotations

from app.federation import protocol  # noqa: F401

__all__ = ["protocol"]
