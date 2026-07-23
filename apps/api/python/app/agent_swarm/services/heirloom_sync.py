"""Heirloom persistence -- Phase 5 Step 6.

Per an explicit scoping decision: the spec's "IPFS + blockchain
attestation" would mean real wallet/private-key management, gas fees,
and a pinning service -- genuine infrastructure and cost, not something
to fake. What's built here is the `HeirloomStore` interface plus a real,
working backend (`PostgresEncryptedHeirloomStore`, AES-256-GCM) and a
documented, explicitly-not-wired stub for the future
IPFS/blockchain backend. Nothing in this file claims to be on-chain when
it isn't -- `IPFSBlockchainHeirloomStore` raises `NotImplementedError`
rather than returning a fake hash/tx id. See ROADMAP.md for the
activation plan once real credentials are available.

Cross-device sync is "simulated" per the same scoping decision: a device
exports its agent's weight snapshot as JSON, another device imports it.
That's a real, working transfer mechanism -- what's not real yet is
doing that transfer *through* IPFS instead of however the two devices
otherwise move a JSON file (the user's own sync channel, a manual copy,
etc.).
"""

from __future__ import annotations

import hashlib
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

NONCE_SIZE = 12  # 96 bits, the standard/recommended AES-GCM nonce size


class HeirloomError(RuntimeError):
    pass


@dataclass(frozen=True)
class HeirloomManifestEntry:
    id: UUID
    agent_id: UUID
    device_id: str
    user_id: str
    backend: str
    content_hash: str
    verified: bool
    created_at: datetime


def _content_hash(snapshot: dict) -> str:
    """Deterministic hash of a weight snapshot -- content-addressed
    identity independent of which backend eventually stores the bytes,
    so a future ipfs_blockchain row can be verified against the same
    hash an existing postgres_encrypted row already committed to."""
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class HeirloomStore(ABC):
    """store/fetch/verify -- the interface every backend implements.
    Callers (the FastAPI router, swarm_coordinator) should depend on
    this, not on a concrete backend, so swapping in the future
    IPFS/blockchain adapter is a config change, not a rewrite."""

    @abstractmethod
    async def store(self, pool, agent_id: UUID, user_id: str, device_id: str, snapshot: dict) -> HeirloomManifestEntry: ...

    @abstractmethod
    async def fetch(self, pool, agent_id: UUID, device_id: str) -> dict | None: ...

    @abstractmethod
    async def verify(self, pool, manifest_id: UUID) -> bool: ...


class PostgresEncryptedHeirloomStore(HeirloomStore):
    """Real, working backend: AES-256-GCM-encrypted weight snapshots in
    Postgres `heirloom_manifest.encrypted_payload`. Requires
    HEIRLOOM_DEVICE_KEY (32 raw bytes, base64 or hex in the env var) --
    raises HeirloomError rather than silently storing plaintext or a
    weak default key if it's unset."""

    def __init__(self, device_key: bytes | None = None):
        self._device_key = device_key or self._load_key()

    @staticmethod
    def _load_key() -> bytes:
        settings = get_settings()
        raw = settings.heirloom_device_key
        if not raw:
            raise HeirloomError(
                "HEIRLOOM_DEVICE_KEY is not set -- heirloom export/import is disabled until a real "
                "32-byte key is configured. Generate one with: python -c "
                "\"import secrets; print(secrets.token_hex(32))\""
            )
        try:
            key = bytes.fromhex(raw)
        except ValueError as exc:
            raise HeirloomError("HEIRLOOM_DEVICE_KEY must be a 64-character hex string (32 bytes)") from exc
        if len(key) != 32:
            raise HeirloomError(f"HEIRLOOM_DEVICE_KEY must decode to exactly 32 bytes, got {len(key)}")
        return key

    def _encrypt(self, snapshot: dict) -> bytes:
        aesgcm = AESGCM(self._device_key)
        nonce = os.urandom(NONCE_SIZE)
        plaintext = json.dumps(snapshot).encode("utf-8")
        ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data=None)
        return nonce + ciphertext  # nonce prefix, standard AEAD storage convention

    def _decrypt(self, payload: bytes) -> dict:
        nonce, ciphertext = payload[:NONCE_SIZE], payload[NONCE_SIZE:]
        aesgcm = AESGCM(self._device_key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data=None)
        return json.loads(plaintext.decode("utf-8"))

    async def store(self, pool, agent_id: UUID, user_id: str, device_id: str, snapshot: dict) -> HeirloomManifestEntry:
        content_hash = _content_hash(snapshot)
        encrypted = self._encrypt(snapshot)
        row = await pool.fetchrow(
            """
            INSERT INTO heirloom_manifest (agent_id, device_id, user_id, backend, content_hash, encrypted_payload, verified)
            VALUES ($1, $2, $3, 'postgres_encrypted', $4, $5, true)
            RETURNING id, created_at
            """,
            agent_id,
            device_id,
            user_id,
            content_hash,
            encrypted,
        )
        return HeirloomManifestEntry(
            id=row["id"],
            agent_id=agent_id,
            device_id=device_id,
            user_id=user_id,
            backend="postgres_encrypted",
            content_hash=content_hash,
            verified=True,
            created_at=row["created_at"],
        )

    async def fetch(self, pool, agent_id: UUID, device_id: str) -> dict | None:
        row = await pool.fetchrow(
            """
            SELECT encrypted_payload FROM heirloom_manifest
            WHERE agent_id = $1 AND device_id = $2 AND backend = 'postgres_encrypted'
            ORDER BY created_at DESC LIMIT 1
            """,
            agent_id,
            device_id,
        )
        if row is None or row["encrypted_payload"] is None:
            return None
        return self._decrypt(bytes(row["encrypted_payload"]))

    async def verify(self, pool, manifest_id: UUID) -> bool:
        row = await pool.fetchrow(
            "SELECT content_hash, encrypted_payload FROM heirloom_manifest WHERE id = $1", manifest_id
        )
        if row is None or row["encrypted_payload"] is None:
            return False
        snapshot = self._decrypt(bytes(row["encrypted_payload"]))
        return _content_hash(snapshot) == row["content_hash"]


class IPFSBlockchainHeirloomStore(HeirloomStore):
    """Documented, NOT wired to real infrastructure. Every method raises
    -- this class exists so the interface shape is settled and swapping
    it in later (once real IPFS pinning + wallet credentials exist) is a
    constructor change, not a redesign. See ROADMAP.md's Phase 7 entry.
    """

    def __init__(self, *_args, **_kwargs):
        raise NotImplementedError(
            "IPFSBlockchainHeirloomStore is a documented interface stub, not a working backend -- "
            "see ROADMAP.md (Phase 7: IPFS/blockchain heirloom adapter activation). Use "
            "PostgresEncryptedHeirloomStore until real IPFS pinning + wallet credentials are configured."
        )

    async def store(self, *_a, **_kw):  # pragma: no cover -- unreachable, __init__ always raises
        raise NotImplementedError

    async def fetch(self, *_a, **_kw):  # pragma: no cover
        raise NotImplementedError

    async def verify(self, *_a, **_kw):  # pragma: no cover
        raise NotImplementedError


async def snapshot_agent_weight(pool, agent_id: UUID) -> dict:
    """Builds the exportable weight snapshot for one agent: its current
    learned state plus enough weight_history to reconstruct how it got
    there (recursive seniority -- a successor agent inheriting this
    heirloom sees the *trajectory*, not just a final number)."""
    agent = await pool.fetchrow(
        """
        SELECT id, name, role, level, model, current_weight, consecutive_successes,
               total_tasks, total_successes, parent_agent_id, mentor_agent_id
        FROM agent_registry WHERE id = $1
        """,
        agent_id,
    )
    if agent is None:
        raise HeirloomError(f"agent {agent_id} not found")

    history = await pool.fetch(
        "SELECT weight, delta, reason, created_at FROM weight_history WHERE agent_id = $1 ORDER BY created_at",
        agent_id,
    )

    return {
        "agent_id": str(agent["id"]),
        "name": agent["name"],
        "role": agent["role"],
        "level": agent["level"],
        "model": agent["model"],
        "current_weight": float(agent["current_weight"]),
        "consecutive_successes": agent["consecutive_successes"],
        "total_tasks": agent["total_tasks"],
        "total_successes": agent["total_successes"],
        "parent_agent_id": str(agent["parent_agent_id"]) if agent["parent_agent_id"] else None,
        "mentor_agent_id": str(agent["mentor_agent_id"]) if agent["mentor_agent_id"] else None,
        "weight_history": [
            {
                "weight": float(h["weight"]),
                "delta": float(h["delta"]),
                "reason": h["reason"],
                "created_at": h["created_at"].isoformat(),
            }
            for h in history
        ],
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }


async def export_heirloom(pool, store: HeirloomStore, agent_id: UUID, user_id: str, device_id: str) -> HeirloomManifestEntry:
    """`user_id` is caller-supplied (POST /heirlooms/{agent_id}/export's
    request body), not derived from the agent itself -- a readiness
    review found this never checked it against the agent's actual owner,
    so `POST /heirlooms/<any-agent-uuid>/export {"user_id": "attacker", ...}`
    succeeded for any existing agent_id, including one belonging to a
    different user, and the resulting heirloom_manifest row then showed
    up under `GET /heirlooms?user_id=attacker`. import_heirloom_to_successor
    (below) already enforces the identical "heirlooms are per-user only"
    guardrail (migrations/0008_agent_swarm.sql) for its own two-agent
    case; this applies the same check here, against the agent's real
    agent_registry.user_id."""
    actual_owner = await pool.fetchval("SELECT user_id FROM agent_registry WHERE id = $1", agent_id)
    if actual_owner != user_id:
        raise HeirloomError(f"agent {agent_id} does not belong to user {user_id!r}")

    snapshot = await snapshot_agent_weight(pool, agent_id)
    return await store.store(pool, agent_id, user_id, device_id, snapshot)


async def import_heirloom_to_successor(
    pool, store: HeirloomStore, source_agent_id: UUID, source_device_id: str, successor_agent_id: UUID
) -> None:
    """Recursive seniority: pulls a senior agent's exported snapshot and
    links the successor to it via agent_registry.parent_agent_id, then
    seeds the successor's weight from the heirloom's current_weight
    rather than starting it back at the neutral prior. Scope guardrail:
    caller must ensure both agents belong to the same user_id --
    heirlooms are per-user only (see migrations/0008_agent_swarm.sql)."""
    snapshot = await store.fetch(pool, source_agent_id, source_device_id)
    if snapshot is None:
        raise HeirloomError(f"no heirloom found for agent {source_agent_id} on device {source_device_id}")

    async with pool.acquire() as conn, conn.transaction():
        source_user = await conn.fetchval("SELECT user_id FROM agent_registry WHERE id = $1", source_agent_id)
        successor_user = await conn.fetchval("SELECT user_id FROM agent_registry WHERE id = $1", successor_agent_id)
        if source_user != successor_user:
            raise HeirloomError("heirlooms are per-user only -- source and successor agents belong to different users")

        await conn.execute(
            "UPDATE agent_registry SET parent_agent_id = $1, current_weight = $2, updated_at = now() WHERE id = $3",
            source_agent_id,
            snapshot["current_weight"],
            successor_agent_id,
        )
        await conn.execute(
            "INSERT INTO weight_history (agent_id, weight, delta, reason) VALUES ($1, $2, $3, 'heirloom_inherited')",
            successor_agent_id,
            snapshot["current_weight"],
            snapshot["current_weight"] - 1.0,
        )
