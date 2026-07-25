"""
protocol.py — the language-agnostic federation wire format.

Everything in this module is designed so that a Python service and the
Node/Express service (Mom-) produce **byte-identical** hashes for the same
logical record. That is what lets the forensic matrix ingest and verify a
chain written by any service, in any language.

Canonicalization rule (the single most important thing to keep in sync):

    canonical(obj) = json.dumps(obj, sort_keys=True,
                                separators=(",", ":"), ensure_ascii=False)

The Node adapter implements the same recursive key-sorted, compact-separator,
UTF-8 serialization. Keep payloads JSON-primitive (str/int/float/bool/None,
lists, dicts) so both languages agree.

Security model, stated honestly:
  - The ``hash`` field makes the log *tamper-evident*: editing any past record
    changes its hash, which breaks every later record's ``prev_hash`` link.
  - The ``sig`` field (HMAC-SHA256 over the hash, keyed by a shared federation
    secret) proves a record was written by a holder of that secret. It is a
    shared-secret MAC, not public-key signing — appropriate for a set of
    services you operate, not for third-party non-repudiation.
  - This is NOT a distributed consensus ledger. It is a local, verifiable
    audit chain. That distinction is the whole point (see __init__.py).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

FEDERATION_VERSION = "1.0"

# 64 zero hex chars — the ``prev_hash`` of the genesis record.
GENESIS_PREV_HASH = "0" * 64

# The shared secret used to sign ledger records. In a real deployment every
# federated service is given the SAME value (env var), so any service can
# verify any other's chain. Falls back to a clearly-labelled dev default that
# the forensic matrix flags as insecure, mirroring the map repo's pattern of
# treating a known placeholder like a missing secret.
_DEV_SECRET = "federation-dev-insecure-secret-change-me"


def federation_secret() -> str:
    """Return the shared federation signing secret from the environment."""
    value = os.environ.get("FEDERATION_SECRET", "").strip()
    return value or _DEV_SECRET


def secret_is_insecure(secret: Optional[str] = None) -> bool:
    """True if the signing secret is empty or the known public dev default."""
    secret = secret if secret is not None else federation_secret()
    return (not secret) or secret == _DEV_SECRET


def _utcnow_iso() -> str:
    """Timezone-aware UTC timestamp, second precision, stable across services."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical(obj: Any) -> str:
    """Deterministic JSON used for hashing. Must match the Node implementation."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ---------------------------------------------------------------------------
# Capability + manifest
# ---------------------------------------------------------------------------
@dataclass
class Capability:
    """One thing a service can do, as advertised to the mediator."""

    name: str  # stable id, e.g. "tax.calculate"
    method: str  # HTTP verb, e.g. "POST"
    path: str  # path relative to the service base_url
    description: str = ""
    # Free-form tag grouping equivalent capabilities across services so the
    # mediator can fail over between them, e.g. "compute", "chat", "search".
    equivalence: Optional[str] = None
    auth_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ServiceManifest:
    """A service's self-description. Serialized to federation/manifest.json."""

    service_id: str
    display_name: str
    kind: str  # "hub" | "service"
    language: str  # "python" | "node"
    base_url: str
    capabilities: list[Capability] = field(default_factory=list)
    health_path: str = "/federation/health"
    audit_path: str = "/federation/audit"
    allowed_origins: list[str] = field(default_factory=list)
    allow_credentials: bool = True
    federation_version: str = FEDERATION_VERSION

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["capabilities"] = [c.to_dict() for c in self.capabilities]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ServiceManifest":
        caps = [Capability(**c) for c in data.get("capabilities", [])]
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        kwargs = {k: v for k, v in data.items() if k in known and k != "capabilities"}
        return cls(capabilities=caps, **kwargs)


# ---------------------------------------------------------------------------
# Audit ledger (the tamper-evident chain)
# ---------------------------------------------------------------------------
def record_hash(
    seq: int,
    ts: str,
    service: str,
    action: str,
    actor: str,
    payload: Any,
    prev_hash: str,
) -> str:
    """SHA-256 over the canonical form of a record's signed fields."""
    body = canonical(
        {
            "seq": seq,
            "ts": ts,
            "service": service,
            "action": action,
            "actor": actor,
            "payload": payload,
            "prev_hash": prev_hash,
        }
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def sign(record_hash_hex: str, secret: Optional[str] = None) -> str:
    """HMAC-SHA256 of the record hash, keyed by the shared federation secret."""
    secret = secret if secret is not None else federation_secret()
    return hmac.new(
        secret.encode("utf-8"), record_hash_hex.encode("utf-8"), hashlib.sha256
    ).hexdigest()


@dataclass
class LedgerRecord:
    """One append-only, hash-linked, signed audit entry."""

    seq: int
    ts: str
    service: str
    action: str
    actor: str
    payload: dict[str, Any]
    prev_hash: str
    hash: str
    sig: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AuditLedger:
    """
    A thread-safe, file-backed, hash-chained append-only audit log.

    The file (``.federation_ledger.json``, gitignored) holds a JSON array of
    records. Each ``append`` links to the previous record's hash; ``verify``
    recomputes the whole chain and reports the first break, which is exactly
    what the forensic matrix uses to detect tampering.
    """

    def __init__(self, service_id: str, path: Optional[Path] = None) -> None:
        self.service_id = service_id
        self.path = path or (Path(__file__).resolve().parent.parent / ".federation_ledger.json")
        self._lock = threading.Lock()
        self._records: list[LedgerRecord] = []
        self._load()

    # -- persistence --------------------------------------------------------
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
            self._records = [LedgerRecord(**r) for r in raw]
        except Exception:
            # A corrupt ledger is itself a forensic signal; start fresh but do
            # not crash the host service on boot.
            self._records = []

    def _save(self) -> None:
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps([r.to_dict() for r in self._records], indent=2))
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    # -- append / read ------------------------------------------------------
    def append(self, action: str, payload: dict[str, Any], actor: str = "") -> LedgerRecord:
        """Append a new signed record linked to the current chain head."""
        with self._lock:
            seq = len(self._records)
            prev_hash = self._records[-1].hash if self._records else GENESIS_PREV_HASH
            ts = _utcnow_iso()
            actor = actor or self.service_id
            h = record_hash(seq, ts, self.service_id, action, actor, payload, prev_hash)
            rec = LedgerRecord(
                seq=seq,
                ts=ts,
                service=self.service_id,
                action=action,
                actor=actor,
                payload=payload,
                prev_hash=prev_hash,
                hash=h,
                sig=sign(h),
            )
            self._records.append(rec)
            self._save()
            return rec

    def records(self, limit: Optional[int] = None) -> list[dict[str, Any]]:
        """Return records (most-recent-last), optionally limited to the tail."""
        with self._lock:
            recs = self._records[-limit:] if limit else list(self._records)
            return [r.to_dict() for r in recs]

    def head(self) -> str:
        """Current chain head hash (genesis sentinel if empty)."""
        with self._lock:
            return self._records[-1].hash if self._records else GENESIS_PREV_HASH

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._records)


def verify_chain(records: list[dict[str, Any]], secret: Optional[str] = None) -> dict[str, Any]:
    """
    Verify a chain of record dicts (from any service, any language).

    Returns a structured report: whether the chain is intact, and the seq of
    the first break with a machine-readable reason. This is pure/stateless so
    the forensic matrix can run it over a remote service's exported chain.
    """
    secret = secret if secret is not None else federation_secret()
    prev_hash = GENESIS_PREV_HASH
    for i, r in enumerate(records):
        # Structural: sequence numbers must be contiguous from 0.
        if r.get("seq") != i:
            return _break(i, "seq_out_of_order", f"expected seq {i}, got {r.get('seq')}")
        # Linkage: prev_hash must match the running head.
        if r.get("prev_hash") != prev_hash:
            return _break(i, "broken_link", "prev_hash does not match prior record hash")
        # Integrity: recompute the content hash.
        expected = record_hash(
            r["seq"],
            r["ts"],
            r["service"],
            r["action"],
            r["actor"],
            r["payload"],
            r["prev_hash"],
        )
        if r.get("hash") != expected:
            return _break(i, "hash_mismatch", "record content was altered after signing")
        # Authenticity: the HMAC must validate under the shared secret.
        if not hmac.compare_digest(r.get("sig", ""), sign(expected, secret)):
            return _break(i, "bad_signature", "signature invalid for the federation secret")
        prev_hash = r["hash"]
    return {
        "intact": True,
        "length": len(records),
        "head": prev_hash,
        "first_break": None,
    }


def _break(index: int, reason: str, detail: str) -> dict[str, Any]:
    return {
        "intact": False,
        "first_break": {"seq": index, "reason": reason, "detail": detail},
    }
