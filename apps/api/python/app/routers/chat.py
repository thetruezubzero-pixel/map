from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import db
from app.agents.chat_agent import ChatAgent
from app.agents.map_intent import MapAction, parse_map_intent

router = APIRouter(tags=["chat"])

chat_agent = ChatAgent()


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)


class ChatGroundingRecord(BaseModel):
    id: str
    name: str
    entity_type: str
    source: str
    license: str | None
    retrieved_at: str
    # Coordinates when the grounded row has geometry -- lets the frontend
    # plot the entities the agent cites on the map (null for a row with no
    # geom, which stays chat-only). See chat_agent._search_grounding.
    lon: float | None = None
    lat: float | None = None


class ChatResponse(BaseModel):
    reply: str
    grounding: list[ChatGroundingRecord]
    # Typed instructions for the frontend to execute against the map (run
    # a search, move the viewport, toggle a layer, ...). This is what makes
    # the agent *operate the map itself* from plain English rather than the
    # user driving every control. Empty for a purely conversational turn.
    # See app/agents/map_intent.py; mirrored by applyMapActions on the web.
    actions: list[MapAction] = []


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    """Direct plain-English conversation with the platform, distinct from
    POST /research's structured multi-agent pipeline. Stateless server-side
    -- the caller resends the full message list each turn -- so this adds
    no new persistence surface. `role` is restricted to user/assistant (see
    ChatMessage) so a caller can't inject a fake system message to override
    ChatAgent's system prompt. See app/agents/chat_agent.py for how answers
    about specific entities get grounded in a live DB lookup rather than
    the model's own training data.

    The response also carries any `actions` the latest user message maps to
    (deterministically, no model call needed -- see app/agents/map_intent.py),
    so the map responds to plain-English commands even with OPENROUTER_API_KEY
    unset. When the model is unreachable but the message did map to actions,
    the deterministic action summary is used as the reply so the user still
    gets a coherent acknowledgement of what the map just did."""
    pool = await db.get_pool()
    messages = [m.model_dump() for m in payload.messages]

    latest_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    actions, action_summary = parse_map_intent(latest_user)

    reply, grounding = await chat_agent.run(pool, messages)
    # If the model degraded to its generic can't-reach-model fallback but we
    # DID execute real map actions, prefer telling the user what happened.
    if action_summary and reply.startswith("I couldn't reach the language model"):
        reply = action_summary

    return ChatResponse(
        reply=reply,
        grounding=[ChatGroundingRecord(**g) for g in grounding],
        actions=actions,
    )
