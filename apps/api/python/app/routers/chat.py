from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import db
from app.agents.chat_agent import ChatAgent

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


class ChatResponse(BaseModel):
    reply: str
    grounding: list[ChatGroundingRecord]


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    """Direct plain-English conversation with the platform, distinct from
    POST /research's structured multi-agent pipeline. Stateless server-side
    -- the caller resends the full message list each turn -- so this adds
    no new persistence surface. `role` is restricted to user/assistant (see
    ChatMessage) so a caller can't inject a fake system message to override
    ChatAgent's system prompt. See app/agents/chat_agent.py for how answers
    about specific entities get grounded in a live DB lookup rather than
    the model's own training data."""
    pool = await db.get_pool()
    reply, grounding = await chat_agent.run(pool, [m.model_dump() for m in payload.messages])
    return ChatResponse(reply=reply, grounding=[ChatGroundingRecord(**g) for g in grounding])
