from __future__ import annotations

import json
import logging
from uuid import UUID

from app.agents.base import Agent
from app.config import get_settings
from app.models import PlanItemCategory, ProjectPlan, ProjectPlanItem
from app.openrouter_client import openrouter_client

logger = logging.getLogger("aether.agents.project_architect")

SYSTEM_PROMPT = """You are the Architect for Aether Sovereign OS, a public-\
records research platform. You are given a JSON "digital twin" snapshot of \
the project's real, current state: database counts, the DAG inventory, the \
route inventory, ROADMAP.md's phase status and non-goals, and recent git \
commits. Ground every recommendation in something the snapshot actually \
shows -- an unwired function, a stalled DAG, a phase marked future, a gap \
between what's built and what ROADMAP.md says is next. Do not invent work \
that has no basis in the snapshot.

ROADMAP.md's "Explicit non-goals" section (included in the snapshot) is a \
hard boundary you must never recommend crossing, and you must never \
recommend editing ROADMAP.md or CLAUDE.md yourself -- those stay human-owned.

Respond with ONLY a JSON object matching this shape:
{
  "items": [
    {
      "title": string,
      "rationale": string (must cite the specific snapshot fact that motivates this),
      "category": one of ["project_plan_doc","code_change","infra_change","documentation","investigation"],
      "safe_to_autoimplement": boolean,
      "target_file": string or null (only for category "documentation" -- a real, existing-or-new \
repo-relative markdown doc path, e.g. "docs/some_topic.md" -- NEVER "CLAUDE.md" or "ROADMAP.md", \
those are rejected outright regardless of what you propose here),
      "content": string or null (only for category "documentation" -- the full proposed new content \
of target_file, not a diff),
      "confidence": number 0.0-1.0 (your own calibrated confidence that this specific item is correct \
and safe -- used downstream to help decide whether a human needs to review it first; be honest, not \
optimistic -- overclaiming confidence doesn't skip review, it's checked against your own track record too)
    }
  ],
  "notes": string or null
}

Only ever set "safe_to_autoimplement": true for:
- category "project_plan_doc" items (updates to the Architect's own status doc, PROJECT_PLAN.md), or
- category "documentation" items that include both target_file and content, proposing a change to an \
existing markdown doc other than CLAUDE.md/ROADMAP.md.
Every other category is a recommendation for a human to act on, never true. Even for the two \
autoimplementable categories, this is a proposal via a real pull request, never a direct edit -- a low \
enough confidence, or a human/CI reviewer, can still stop it. Rank items with the most important \
first. 3-7 items. Always write title/rationale/notes/content in English."""


class ProjectArchitectAgent(Agent):
    name = "project_architect"

    async def run(
        self, snapshot: dict, job_id: UUID | None = None, model: str | None = None
    ) -> ProjectPlan:
        """`model` lets swarm_coordinator-style callers pin this run to a
        specific model instance, same convention as the other 3 agents."""
        settings = get_settings()
        model_used, response = await openrouter_client.complete(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(snapshot, default=str)},
            ],
            model=model or settings.openrouter_default_model,
            fallback_models=[settings.openrouter_fast_model, settings.openrouter_fallback_model],
            temperature=0.2,
            max_tokens=1500,
        )

        text = openrouter_client.extract_text(response)
        plan = self._parse(text, model_used)

        await self.audit(
            job_id,
            "generate_plan",
            {"model": model_used, "plan": plan.model_dump(mode="json")},
        )
        return plan

    def _parse(self, text: str, model_used: str) -> ProjectPlan:
        try:
            start, end = text.index("{"), text.rindex("}") + 1
            data = json.loads(text[start:end])
            items = []
            for raw in data.get("items", []):
                category = PlanItemCategory(raw.get("category"))
                target_file = raw.get("target_file") or None
                # Defense in depth: never trust the model's own
                # safe_to_autoimplement=true. project_plan_doc is always
                # eligible (architect_committer.py re-checks this too);
                # documentation is only eligible if the model actually
                # supplied a target_file + content -- change_proposer.py's
                # _assert_file_allowlisted is the real security boundary
                # (it rejects CLAUDE.md/ROADMAP.md/non-markdown outright
                # regardless of this flag), this is just the first filter.
                safe_to_autoimplement = bool(raw.get("safe_to_autoimplement")) and (
                    category == PlanItemCategory.project_plan_doc
                    or (category == PlanItemCategory.documentation and bool(target_file) and bool(raw.get("content")))
                )
                items.append(
                    ProjectPlanItem(
                        title=raw["title"],
                        rationale=raw["rationale"],
                        category=category,
                        safe_to_autoimplement=safe_to_autoimplement,
                        target_file=target_file,
                        content=raw.get("content") or None,
                        confidence=min(max(float(raw.get("confidence", 0.5)), 0.0), 1.0),
                    )
                )
            if not items:
                raise ValueError("empty items list")
            return ProjectPlan(items=items, reasoning_model=model_used, notes=data.get("notes"))
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            logger.warning("failed to parse architect plan output, using safe default: %s", exc)
            return ProjectPlan(
                items=[
                    ProjectPlanItem(
                        title="Review project state manually",
                        rationale="The architect's plan output could not be parsed this cycle.",
                        category=PlanItemCategory.investigation,
                        safe_to_autoimplement=False,
                    )
                ],
                reasoning_model=model_used,
                notes="fallback plan: model output could not be parsed",
            )
