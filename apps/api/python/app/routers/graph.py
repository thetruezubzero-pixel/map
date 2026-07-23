from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import db

router = APIRouter(prefix="/graph", tags=["graph"])


class GraphNode(BaseModel):
    id: str
    name: str
    entity_type: str
    source: str


class GraphEdge(BaseModel):
    source: str
    target: str
    relation_type: str
    edge_source: str


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class ResolutionCandidate(BaseModel):
    id: str
    entity_a_id: str
    entity_a_name: str
    entity_b_id: str
    entity_b_name: str
    confidence: float
    match_basis: dict
    status: str


class ReviewDecision(BaseModel):
    decision: str  # "confirm" | "reject"
    reviewed_by: str | None = None


@router.get("/{entity_id}", response_model=GraphResponse)
async def get_entity_graph(entity_id: UUID, depth: int = 1) -> GraphResponse:
    """Business entity graph for a single node's neighborhood (D3.js
    force-directed view in the frontend). depth=1 is direct edges only;
    depth=2 also pulls in each neighbor's neighbors. Business entities
    only -- see ROADMAP.md."""
    depth = max(1, min(depth, 2))
    pool = await db.get_pool()

    root = await pool.fetchrow(
        "SELECT id, name, entity_type, source FROM research_entities WHERE id = $1", entity_id
    )
    if root is None:
        raise HTTPException(status_code=404, detail="entity not found")

    node_ids = {root["id"]}
    frontier = {root["id"]}
    edges_seen: dict[tuple, dict] = {}

    for _ in range(depth):
        if not frontier:
            break
        rows = await pool.fetch(
            """
            SELECT parent_entity_id, child_entity_id, relation_type, source
            FROM entity_relationships
            WHERE parent_entity_id = ANY($1::uuid[]) OR child_entity_id = ANY($1::uuid[])
            """,
            list(frontier),
        )
        next_frontier = set()
        for row in rows:
            key = (row["parent_entity_id"], row["child_entity_id"], row["relation_type"])
            edges_seen[key] = dict(row)
            for eid in (row["parent_entity_id"], row["child_entity_id"]):
                if eid not in node_ids:
                    next_frontier.add(eid)
                node_ids.add(eid)
        frontier = next_frontier

    node_rows = await pool.fetch(
        "SELECT id, name, entity_type, source FROM research_entities WHERE id = ANY($1::uuid[])",
        list(node_ids),
    )

    nodes = [
        GraphNode(id=str(r["id"]), name=r["name"], entity_type=r["entity_type"], source=r["source"])
        for r in node_rows
    ]
    edges = [
        GraphEdge(
            source=str(e["parent_entity_id"]),
            target=str(e["child_entity_id"]),
            relation_type=e["relation_type"],
            edge_source=e["source"],
        )
        for e in edges_seen.values()
    ]

    return GraphResponse(nodes=nodes, edges=edges)


@router.get("/review/queue", response_model=list[ResolutionCandidate])
async def get_review_queue(limit: int = 50) -> list[ResolutionCandidate]:
    """Pending entity-resolution matches below the auto-confirm threshold,
    for a human to confirm or reject. See app/graph/resolve.py."""
    pool = await db.get_pool()
    rows = await pool.fetch(
        """
        SELECT c.id, c.entity_a_id, a.name AS a_name, c.entity_b_id, b.name AS b_name,
               c.confidence, c.match_basis, c.status
        FROM entity_resolution_candidates c
        JOIN research_entities a ON a.id = c.entity_a_id
        JOIN research_entities b ON b.id = c.entity_b_id
        WHERE c.status = 'pending_review'
        ORDER BY c.confidence DESC, c.created_at ASC
        LIMIT $1
        """,
        max(1, min(limit, 200)),
    )

    import json

    return [
        ResolutionCandidate(
            id=str(r["id"]),
            entity_a_id=str(r["entity_a_id"]),
            entity_a_name=r["a_name"],
            entity_b_id=str(r["entity_b_id"]),
            entity_b_name=r["b_name"],
            confidence=float(r["confidence"]),
            match_basis=json.loads(r["match_basis"]) if isinstance(r["match_basis"], str) else r["match_basis"],
            status=r["status"],
        )
        for r in rows
    ]


@router.post("/review/{candidate_id}")
async def review_candidate(candidate_id: UUID, decision: ReviewDecision) -> dict:
    if decision.decision not in ("confirm", "reject"):
        raise HTTPException(status_code=400, detail="decision must be 'confirm' or 'reject'")

    pool = await db.get_pool()
    candidate = await pool.fetchrow(
        "SELECT entity_a_id, entity_b_id, status FROM entity_resolution_candidates WHERE id = $1",
        candidate_id,
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    if candidate["status"] != "pending_review":
        raise HTTPException(status_code=409, detail=f"candidate already {candidate['status']}")

    new_status = "confirmed" if decision.decision == "confirm" else "rejected"

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """
            UPDATE entity_resolution_candidates
            SET status = $2, reviewed_by = $3, reviewed_at = now()
            WHERE id = $1
            """,
            candidate_id,
            new_status,
            decision.reviewed_by,
        )
        if new_status == "confirmed":
            await conn.execute(
                """
                INSERT INTO entity_relationships (parent_entity_id, child_entity_id, relation_type, source)
                VALUES ($1, $2, 'same_as', 'entity_resolution_manual_review')
                ON CONFLICT DO NOTHING
                """,
                candidate["entity_a_id"],
                candidate["entity_b_id"],
            )

    return {"id": str(candidate_id), "status": new_status}
