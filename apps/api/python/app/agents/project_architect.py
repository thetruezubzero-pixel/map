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
      "safe_to_autoimplement": boolean
    }
  ],
  "notes": string or null
}

Only ever set "safe_to_autoimplement": true for category "project_plan_doc" \
items -- i.e. updates to the Architect's own status doc, PROJECT_PLAN.md. \
Every other category is a recommendation for a human to act on, never true. \
Rank items with the most important first. 3-7 items."""


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
                items.append(
                    ProjectPlanItem(
                        title=raw["title"],
                        rationale=raw["rationale"],
                        category=category,
                        # Defense in depth: never trust the model's own
                        # safe_to_autoimplement=true for anything but the
                        # one category architect_committer.py is allowed
                        # to act on, regardless of what it claims.
                        safe_to_autoimplement=bool(raw.get("safe_to_autoimplement"))
                        and category == PlanItemCategory.project_plan_doc,
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
