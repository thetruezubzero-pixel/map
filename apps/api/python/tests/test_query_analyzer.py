from app.agents.query_analyzer import QueryAnalyzerAgent
from app.models import EntityType


def test_parse_valid_json():
    agent = QueryAnalyzerAgent()
    text = (
        '{"normalized_query": "Acme subsidiaries", '
        '"entity_types": ["business"], '
        '"candidate_sources": ["opencorporates"], '
        '"notes": null}'
    )
    plan = agent._parse(text, "acme subsidiaries?", "test-model")
    assert plan.entity_types == [EntityType.business]
    assert plan.candidate_sources == ["opencorporates"]
    assert plan.reasoning_model == "test-model"


def test_parse_ignores_out_of_allowlist_types():
    agent = QueryAnalyzerAgent()
    text = '{"normalized_query": "x", "entity_types": ["business", "person"], "candidate_sources": []}'
    plan = agent._parse(text, "x", "test-model")
    # "person" is not a valid EntityType and must be silently dropped, not
    # crash the pipeline -- see ROADMAP.md: no individual profiling.
    assert plan.entity_types == [EntityType.business]


def test_parse_falls_back_safely_on_garbage_output():
    agent = QueryAnalyzerAgent()
    plan = agent._parse("not json at all", "original query", "test-model")
    assert plan.normalized_query == "original query"
    assert plan.entity_types == [EntityType.business]
    assert "fallback" in (plan.notes or "")


def test_entity_type_has_no_person_variant():
    assert "person" not in EntityType._value2member_map_
