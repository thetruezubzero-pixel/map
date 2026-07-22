from app.agent_swarm.services.knowledge_distiller import (
    Exemplar,
    build_distilled_system_prompt,
    query_analyzer_output_key,
)


def test_query_analyzer_output_key_sorts_entity_types():
    assert query_analyzer_output_key({"entity_types": ["news_mention", "business"]}) == "business,news_mention"


def test_query_analyzer_output_key_empty_list():
    assert query_analyzer_output_key({"entity_types": []}) == "empty"


def test_build_distilled_system_prompt_unchanged_with_no_exemplars():
    base = "You are a query analyzer."
    assert build_distilled_system_prompt(base, []) == base


def test_build_distilled_system_prompt_includes_exemplar_content():
    base = "You are a query analyzer."
    exemplars = [
        Exemplar(
            input_query="Acme Corp registration",
            output_key="business",
            consensus_output={"entity_types": ["business"], "normalized_query": "Acme Corp registration"},
        )
    ]
    result = build_distilled_system_prompt(base, exemplars)
    assert base in result
    assert "Acme Corp registration" in result
    assert "Example 1" in result
