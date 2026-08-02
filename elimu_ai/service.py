"""
elimu_ai/service.py

FastAPI entry point — the only web-facing layer.

Responsibilities:
  - Receive HTTP requests
  - Validate input via Pydantic
  - Call run_agent()
  - Return JSON

Nothing else.  No business logic.  No Gemini.  No Qdrant.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from elimu_ai.agent import run_agent
from elimu_ai.config import SYSTEM_NAME

app = FastAPI(
    title=SYSTEM_NAME,
    description="Autonomous educational AI for Kenyan learners.",
    version="2.0.0",
)


# ── Request / Response schemas ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: List[Dict[str, str]] = Field(default_factory=list)


class ChatResponse(BaseModel):
    success: bool
    persona: str
    answer: str
    sources: List[str]
    tools: List[str]


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "status": "running",
        "service": SYSTEM_NAME,
        "version": "2.0.0",
    }


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    try:
        result = run_agent(
            question=req.message,
            history=req.history,
        )
        return ChatResponse(
            success=True,
            persona=result["persona"],
            answer=result["answer"],
            sources=result["sources"],
            tools=result["tools"],
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
