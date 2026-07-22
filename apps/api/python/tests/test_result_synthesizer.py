import asyncio
from datetime import datetime, timezone

from app.agents.result_synthesizer import ResultSynthesizerAgent
from app.models import EntityType, ResearchPlan, SourcedRecord


def _record(name, entity_type, source, retrieved_at=None, metadata=None):
    return SourcedRecord(
        name=name,
        entity_type=entity_type,
        source=source,
        retrieved_at=retrieved_at or datetime.now(timezone.utc),
        metadata=metadata or {},
    )


def test_build_timeline_orders_by_retrieved_at():
    agent = ResultSynthesizerAgent()
    early = _record("Old Filing", EntityType.government_filing, "sec_edgar", datetime(2020, 1, 1, tzinfo=timezone.utc))
    late = _record("New Filing", EntityType.government_filing, "sec_edgar", datetime(2026, 1, 1, tzinfo=timezone.utc))
    timeline = agent._build_timeline([late, early])
    assert [e.date for e in timeline] == ["2020-01-01", "2026-01-01"]


def test_build_relationships_currently_always_empty():
    """Regression/documentation test: _build_relationships reads
    metadata["parent_company"], but no record producer in this codebase
    ever sets that key (data_retriever.py's _fetch_opencorporates only
    calls OpenCorporates' search endpoint, which doesn't expose
    parent/controlling-entity data) -- confirmed by grepping the whole
    apps/api/python tree for "parent_company": this is the only site.
    This test locks in that current, documented-as-a-gap behavior so a
    future change to data_retriever.py that starts populating the field
    is a deliberate, visible change to this test, not a silent one."""
    agent = ResultSynthesizerAgent()
    records = [
        _record("Acme Inc", EntityType.business, "opencorporates", metadata={"jurisdiction": "us_de"}),
        _record("Acme Subsidiary LLC", EntityType.business, "opencorporates", metadata={"company_number": "123"}),
    ]
    assert agent._build_relationships(records) == []


def test_build_relationships_would_fire_if_parent_company_were_populated():
    agent = ResultSynthesizerAgent()
    records = [_record("Acme Subsidiary LLC", EntityType.business, "opencorporates", metadata={"parent_company": "Acme Inc"})]
    relationships = agent._build_relationships(records)
    assert len(relationships) == 1
    assert relationships[0].parent == "Acme Inc"
    assert relationships[0].child == "Acme Subsidiary LLC"


def test_build_relationships_ignores_non_business_records():
    agent = ResultSynthesizerAgent()
    records = [_record("Some Article", EntityType.news_mention, "newsapi", metadata={"parent_company": "Acme Inc"})]
    assert agent._build_relationships(records) == []


def test_summarize_falls_back_safely_when_openrouter_fails(monkeypatch):
    """_summarize must never let an OpenRouter failure crash the job --
    confirmed live earlier this session that a fully-invalid API key
    correctly hits this exact fallback path, not an uncaught exception."""
    from app.agents import result_synthesizer as rs_module

    async def _boom(*args, **kwargs):
        raise RuntimeError("openrouter unreachable")

    monkeypatch.setattr(rs_module.openrouter_client, "complete", _boom)

    agent = ResultSynthesizerAgent()
    plan = ResearchPlan(normalized_query="acme", entity_types=[EntityType.business], candidate_sources=["opencorporates"], reasoning_model="test")
    records = [_record("Acme Inc", EntityType.business, "opencorporates")]
    summary = asyncio.run(agent._summarize(plan, records, settings=None))
    assert "Found 1 public record" in summary


def test_summarize_returns_canned_message_for_no_records():
    agent = ResultSynthesizerAgent()
    plan = ResearchPlan(normalized_query="acme", entity_types=[], candidate_sources=[], reasoning_model="test")
    summary = asyncio.run(agent._summarize(plan, [], settings=None))
    assert summary == "No public records matched this query."
