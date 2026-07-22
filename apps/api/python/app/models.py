from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class EntityType(str, Enum):
    """Mirrors the DB-level allowlist in migrations/0002_phase2.sql.
    There is intentionally no `person` type -- see ROADMAP.md."""

    business = "business"
    government_filing = "government_filing"
    location = "location"
    poi = "poi"
    news_mention = "news_mention"


class SourcedRecord(BaseModel):
    """Every record surfaced by an agent must carry provenance."""

    name: str
    entity_type: EntityType
    source: str
    license: str | None = None
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)
    url: str | None = None
    lat: float | None = None
    lon: float | None = None
    metadata: dict = Field(default_factory=dict)


class ResearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    requested_by: str | None = None


class ResearchPlan(BaseModel):
    """Output of QUERY_ANALYZER_AGENT."""

    normalized_query: str
    entity_types: list[EntityType]
    candidate_sources: list[str]
    reasoning_model: str
    notes: str | None = None


class ResearchTimelineEvent(BaseModel):
    date: str
    description: str
    source: str


class EntityRelationship(BaseModel):
    parent: str
    child: str
    relation_type: str = "subsidiary"
    source: str


class ResearchReport(BaseModel):
    """Output of RESULT_SYNTHESIZER_AGENT."""

    summary: str
    records: list[SourcedRecord]
    timeline: list[ResearchTimelineEvent] = Field(default_factory=list)
    relationships: list[EntityRelationship] = Field(default_factory=list)
    requires_human_review: bool = True


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    awaiting_review = "awaiting_review"
    completed = "completed"
    failed = "failed"


class ResearchJobResponse(BaseModel):
    job_id: str
    status: JobStatus


class ResearchJobDetail(ResearchJobResponse):
    query: str
    requested_by: str | None
    result: ResearchReport | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class PlanItemCategory(str, Enum):
    """`project_plan_doc` (via architect_committer.py) and, as of Phase
    5c, `documentation` (via change_proposer.py, allowlisted docs only --
    see ROADMAP.md "Phase 5c: widening safe_to_autoimplement") are the
    only categories ever autoimplementable -- everything else is a real,
    surfaced recommendation that stays advisory (shown on the /architect
    dashboard, never auto-implemented), same "advisory unless a human
    reviews it" shape as task_history.consensus_output."""

    project_plan_doc = "project_plan_doc"
    code_change = "code_change"
    infra_change = "infra_change"
    documentation = "documentation"
    investigation = "investigation"


class ProjectPlanItem(BaseModel):
    title: str
    rationale: str
    category: PlanItemCategory
    safe_to_autoimplement: bool = False
    # Only meaningful for category=documentation: which allowlisted doc
    # file to write, the proposed new content, and the model's own
    # self-reported confidence in this specific item (0.0-1.0) --
    # change_proposer.py multiplies this by the architect's tracked
    # agent_registry.current_weight to decide auto-merge eligibility, so
    # this is one real input to that gate, not the whole gate.
    target_file: str | None = None
    content: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ProjectPlan(BaseModel):
    """Output of PROJECT_ARCHITECT_AGENT, grounded in one project_snapshots
    row (see app/agent_swarm/introspection.py)."""

    items: list[ProjectPlanItem]
    reasoning_model: str
    notes: str | None = None
