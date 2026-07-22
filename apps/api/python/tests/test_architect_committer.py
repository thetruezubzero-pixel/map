import pytest

from app.agent_swarm.services import architect_committer as ac
from app.models import PlanItemCategory, ProjectPlan, ProjectPlanItem


@pytest.mark.parametrize("branch", ["main", "Main", "MAIN", "master", " main ", "  Master  "])
def test_assert_never_main_rejects_protected_branches(branch):
    with pytest.raises(ac.ArchitectCommitError):
        ac._assert_never_main(branch)


def test_assert_never_main_allows_real_branch_names():
    ac._assert_never_main("agent/architect/20260101-update-plan")  # must not raise


def test_slugify_produces_safe_branch_fragment():
    assert ac._slugify("Wire apply_decay() to a scheduled job!") == "wire-apply-decay-to-a-scheduled-job"
    assert ac._slugify("") == "update"
    assert len(ac._slugify("x" * 200)) <= 40


def test_render_plan_doc_includes_every_item_and_flags_autoimplementable():
    plan = ProjectPlan(
        items=[
            ProjectPlanItem(
                title="Update plan doc",
                rationale="stale",
                category=PlanItemCategory.project_plan_doc,
                safe_to_autoimplement=True,
            ),
            ProjectPlanItem(
                title="Wire apply_decay",
                rationale="zero callers",
                category=PlanItemCategory.code_change,
                safe_to_autoimplement=False,
            ),
        ],
        reasoning_model="test-model",
        notes="some notes",
    )
    doc = ac._render_plan_doc(plan, "test snapshot summary")
    assert "Update plan doc" in doc
    assert "Wire apply_decay" in doc
    assert "(auto-implementable)" in doc  # only the first item should get this flag
    assert doc.count("(auto-implementable)") == 1
    assert "some notes" in doc
    assert "test snapshot summary" in doc
    # The architect never merges its own PRs -- the doc it writes about
    # itself must say so, not just the code that enforces it.
    assert "never merges" in doc.lower()
