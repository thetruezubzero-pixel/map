from app.agents.project_architect import ProjectArchitectAgent
from app.models import PlanItemCategory


def test_parse_valid_json():
    agent = ProjectArchitectAgent()
    text = (
        '{"items": [{"title": "Wire apply_decay to a scheduled job", '
        '"rationale": "credit_assigner.apply_decay has zero callers anywhere in the repo", '
        '"category": "code_change", "safe_to_autoimplement": false}], "notes": null}'
    )
    plan = agent._parse(text, "test-model")
    assert len(plan.items) == 1
    assert plan.items[0].category == PlanItemCategory.code_change
    assert plan.reasoning_model == "test-model"


def test_parse_falls_back_safely_on_garbage_output():
    agent = ProjectArchitectAgent()
    plan = agent._parse("not json at all", "test-model")
    assert len(plan.items) == 1
    assert plan.items[0].category == PlanItemCategory.investigation
    assert plan.items[0].safe_to_autoimplement is False
    assert "fallback" in (plan.notes or "")


def test_parse_falls_back_on_empty_items():
    agent = ProjectArchitectAgent()
    plan = agent._parse('{"items": [], "notes": null}', "test-model")
    assert len(plan.items) == 1
    assert plan.items[0].safe_to_autoimplement is False


def test_safe_to_autoimplement_forced_false_outside_project_plan_doc():
    """Defense in depth: architect_committer.py only ever acts on
    project_plan_doc items, but this must be enforced here too, not just
    trusted from the model's own output -- a model claiming
    safe_to_autoimplement=true on a code_change item must never survive
    parsing as true."""
    agent = ProjectArchitectAgent()
    text = (
        '{"items": [{"title": "Rewrite the auth system", "rationale": "because", '
        '"category": "code_change", "safe_to_autoimplement": true}], "notes": null}'
    )
    plan = agent._parse(text, "test-model")
    assert plan.items[0].category == PlanItemCategory.code_change
    assert plan.items[0].safe_to_autoimplement is False


def test_safe_to_autoimplement_preserved_for_project_plan_doc():
    agent = ProjectArchitectAgent()
    text = (
        '{"items": [{"title": "Update plan doc", "rationale": "stale", '
        '"category": "project_plan_doc", "safe_to_autoimplement": true}], "notes": null}'
    )
    plan = agent._parse(text, "test-model")
    assert plan.items[0].category == PlanItemCategory.project_plan_doc
    assert plan.items[0].safe_to_autoimplement is True


def test_unknown_category_falls_back_safely():
    agent = ProjectArchitectAgent()
    text = '{"items": [{"title": "x", "rationale": "y", "category": "not_a_real_category", "safe_to_autoimplement": true}]}'
    plan = agent._parse(text, "test-model")
    assert plan.items[0].category == PlanItemCategory.investigation
    assert plan.items[0].safe_to_autoimplement is False


def test_documentation_safe_to_autoimplement_preserved_with_target_and_content():
    """Phase 5c: documentation items are autoimplementable too, but only
    when the model actually supplied a target_file and content --
    change_proposer.py's allowlist is the real security boundary (it
    rejects CLAUDE.md/ROADMAP.md/non-markdown outright), this is just
    the first defense-in-depth filter."""
    agent = ProjectArchitectAgent()
    text = (
        '{"items": [{"title": "Document the new /chat route", "rationale": "undocumented", '
        '"category": "documentation", "safe_to_autoimplement": true, '
        '"target_file": "docs/chat.md", "content": "# Chat\\n\\ndetails", "confidence": 0.9}]}'
    )
    plan = agent._parse(text, "test-model")
    item = plan.items[0]
    assert item.category == PlanItemCategory.documentation
    assert item.safe_to_autoimplement is True
    assert item.target_file == "docs/chat.md"
    assert item.content == "# Chat\n\ndetails"
    assert item.confidence == 0.9


def test_documentation_forced_false_without_target_file():
    agent = ProjectArchitectAgent()
    text = (
        '{"items": [{"title": "Document something", "rationale": "why", '
        '"category": "documentation", "safe_to_autoimplement": true}]}'
    )
    plan = agent._parse(text, "test-model")
    item = plan.items[0]
    assert item.category == PlanItemCategory.documentation
    assert item.safe_to_autoimplement is False


def test_confidence_clamped_to_valid_range():
    agent = ProjectArchitectAgent()
    text = (
        '{"items": [{"title": "x", "rationale": "y", "category": "investigation", '
        '"safe_to_autoimplement": false, "confidence": 5.0}]}'
    )
    plan = agent._parse(text, "test-model")
    assert plan.items[0].confidence == 1.0
