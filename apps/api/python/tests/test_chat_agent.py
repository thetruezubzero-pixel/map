import asyncio
from datetime import datetime, timezone

from app.agents.chat_agent import ChatAgent


class _FakePool:
    """Returns one canned grounding row for any query -- enough to test
    ChatAgent.run's fallback formatting without a real database."""

    async def fetch(self, *a, **k):
        return [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "name": "Acme Test Widgets LLC",
                "entity_type": "business",
                "source": "opencorporates",
                "license": "CC0",
                "retrieved_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "lon": -97.7431,
                "lat": 30.2672,
            }
        ]


async def _noop_audit(self, job_id, action, detail):
    # Agent.audit() (app/agents/base.py) always goes through the real,
    # global app.db.get_pool() regardless of what pool a caller passed
    # into run() -- true of every agent, not something new here. Every
    # existing agent test in this repo (see test_result_synthesizer.py)
    # avoids this by calling internal methods directly instead of run();
    # ChatAgent.run doesn't expose an internal method that skips the
    # OpenRouter call, so this monkeypatches audit() to a no-op instead,
    # confirmed necessary live: without it, a second asyncio.run() in the
    # same pytest process crashes with asyncpg "another operation is in
    # progress" (the module-global pool from the first test's event loop
    # gets reused after that loop is already closed).
    return None


def test_run_falls_back_safely_when_openrouter_fails_and_lists_grounding(monkeypatch):
    """ChatAgent.run must never let an OpenRouter failure crash the
    request -- confirmed live this session that a real 401 (no funded
    OpenRouter key) correctly hits this exact fallback path. The fallback
    should still surface whatever grounding records were found, not just
    a bare error."""
    from app.agents import chat_agent as chat_agent_module

    async def _boom(*args, **kwargs):
        raise RuntimeError("openrouter unreachable")

    monkeypatch.setattr(chat_agent_module.openrouter_client, "complete", _boom)
    monkeypatch.setattr(ChatAgent, "audit", _noop_audit)

    agent = ChatAgent()
    reply, grounding = asyncio.run(agent.run(_FakePool(), [{"role": "user", "content": "acme test widgets"}]))

    assert "Acme Test Widgets LLC" in reply
    assert len(grounding) == 1
    assert grounding[0]["name"] == "Acme Test Widgets LLC"
    # Grounding carries coordinates so the frontend can plot the cited
    # entity on the map (Combine A).
    assert grounding[0]["lon"] == -97.7431
    assert grounding[0]["lat"] == 30.2672


def test_run_skips_grounding_lookup_for_empty_latest_user_message(monkeypatch):
    """No pool query should even fire if there's no user message content
    to ground against (e.g. the conversation is assistant-only so far)."""

    class _NoQueryPool:
        async def fetch(self, *a, **k):
            raise AssertionError("should not query the DB when there's no user message to ground")

    async def _fake_complete(*args, **kwargs):
        return "test-model", {"choices": [{"message": {"content": "ok"}}]}

    import app.agents.chat_agent as chat_agent_module

    monkeypatch.setattr(chat_agent_module.openrouter_client, "complete", _fake_complete)
    monkeypatch.setattr(ChatAgent, "audit", _noop_audit)

    agent = ChatAgent()
    reply, grounding = asyncio.run(agent.run(_NoQueryPool(), [{"role": "assistant", "content": "hi"}]))

    assert grounding == []
    assert reply == "ok"
