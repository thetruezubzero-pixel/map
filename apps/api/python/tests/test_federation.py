"""
Tests for the Aether federation adapter.

Exercises the tamper-evident audit ledger and the ``/federation/*`` HTTP
surface. The router is mounted on a minimal FastAPI app so the test does not
require the full research/graph/streaming dependency stack to be installed.
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

import httpx

from app.federation import adapter, hub_client, protocol
from app.federation.protocol import AuditLedger, verify_chain


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(adapter.router)
    return TestClient(app)


# -- ledger ----------------------------------------------------------------
def test_ledger_chain_intact(tmp_path):
    led = AuditLedger(service_id="aether", path=tmp_path / "l.json")
    led.append("boot", {"n": 0})
    led.append("query", {"n": 1})
    assert verify_chain(led.records())["intact"]


def test_ledger_detects_tampering(tmp_path):
    led = AuditLedger(service_id="aether", path=tmp_path / "l.json")
    led.append("query", {"source": "sec_edgar"})
    led.append("query", {"source": "osm"})
    recs = led.records()
    recs[0]["payload"]["source"] = "tampered"
    report = verify_chain(recs)
    assert not report["intact"]
    assert report["first_break"]["reason"] == "hash_mismatch"


def test_async_record_helper_appends(tmp_path):
    led = AuditLedger(service_id="aether", path=tmp_path / "l.json")
    original = adapter.ledger
    adapter.ledger = led
    try:
        asyncio.run(adapter.record("research.create-job", {"job": "x"}))
    finally:
        adapter.ledger = original
    assert len(led) == 1
    assert led.records()[0]["action"] == "research.create-job"


# -- HTTP surface ----------------------------------------------------------
def test_federation_health():
    resp = _client().get("/federation/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service_id"] == "aether"
    assert body["federation_version"] == protocol.FEDERATION_VERSION


def test_federation_manifest_is_readonly_scope():
    resp = _client().get("/federation/manifest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service_id"] == "aether"
    names = {c["name"] for c in body["capabilities"]}
    # Only read/analytics/research capabilities -- no person/write surface.
    assert names == {
        "research.create-job",
        "graph.query",
        "analytics.top-entity-types",
    }


def test_federation_audit_export_verifiable():
    resp = _client().get("/federation/audit")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "aether"
    assert verify_chain(body["records"])["intact"]


# -- outbound hub client ---------------------------------------------------
def test_hub_client_disabled_by_default(monkeypatch):
    monkeypatch.delenv("FEDERATION_HUB_URL", raising=False)
    assert hub_client.enabled() is False
    # Disabled calls are safe no-ops that report False without any network.
    assert asyncio.run(hub_client.register({"service_id": "aether"})) is False


def test_hub_client_register_and_emit_hit_expected_endpoints(monkeypatch):
    monkeypatch.setenv("FEDERATION_HUB_URL", "http://hub.local")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    assert asyncio.run(
        hub_client.register({"service_id": "aether"}, transport=transport)
    ) is True
    assert asyncio.run(
        hub_client.emit("service.aether", "t", {"n": 1}, "aether", transport=transport)
    ) is True

    paths = [p for p, _ in seen]
    assert "/federation/register" in paths
    assert "/federation/bus/publish" in paths
    publish_params = dict(seen[1][1])
    assert publish_params["source"] == "aether"
    assert publish_params["topic"] == "service.aether"


def test_announce_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("FEDERATION_HUB_URL", raising=False)
    assert asyncio.run(adapter.announce()) == {"enabled": False}
