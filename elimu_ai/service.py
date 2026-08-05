"""
elimu_ai/service.py

FastAPI application — the sole HTTP-facing layer.

Responsibilities:
  - Configure logging (delegates to logging_config.py).
  - Receive and validate HTTP requests.
  - Call run_agent().
  - Return structured JSON.
  - Expose health and scheduler status endpoints.

Endpoints:
  GET  /                  → service info
  GET  /health            → liveness + dependency health
  POST /ask               → main chat endpoint
  POST /chat              → backward-compat alias for /ask
  GET  /scheduler/status  → background worker status

No business logic. No Gemini calls. No Qdrant calls.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from elimu_ai.agent import run_agent
from elimu_ai.config import SYSTEM_NAME, SYSTEM_VERSION
from elimu_ai.logging_config import configure_logging

# Configure logging once, before anything else logs
configure_logging()
logger = logging.getLogger(__name__)

# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title=SYSTEM_NAME,
    description="Autonomous educational AI for Kenyan learners — ElimuTalks & Elimu Library.",
    version=SYSTEM_VERSION,
)

# ── Schemas ───────────────────────────────────────────────────────────────────

class AskRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="User's question")
    history: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Prior conversation turns [{role, content}]",
    )


class AskResponse(BaseModel):
    success: bool
    persona: str
    answer: str
    sources: List[str]
    tools: List[str]


# ── Exception handler ─────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled exception on %s: %s", request.url.path, exc, exc_info=True
    )
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "detail": "An internal error occurred. Please try again.",
        },
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "status":  "running",
        "service": SYSTEM_NAME,
        "version": SYSTEM_VERSION,
    }


@app.get("/health")
def health() -> Dict[str, Any]:
    """
    Liveness + dependency health probe.
    Returns 200 with a status of "ok" or "degraded".
    """
    from elimu_ai.health import get_health
    report = get_health()
    return report


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    """
    Primary chat endpoint.

    Accepts a message and optional conversation history.
    Returns persona, answer, sources, and tools used.
    """
    logger.info("POST /ask message=%r", req.message[:80])
    try:
        result = run_agent(question=req.message, history=req.history)
        return AskResponse(
            success=True,
            persona=result["persona"],
            answer=result["answer"],
            sources=result["sources"],
            tools=result["tools"],
        )
    except Exception as exc:
        logger.error("POST /ask failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Agent error — please try again.")


@app.post("/chat", response_model=AskResponse, include_in_schema=False)
def chat(req: AskRequest) -> AskResponse:
    """Backward-compatible alias for /ask."""
    return ask(req)


@app.get("/scheduler/status")
def get_scheduler_status() -> Dict[str, Any]:
    """Return current background scheduler status."""
    try:
        from elimu_ai.scheduler import get_status
        return get_status()
    except Exception as exc:
        logger.warning("Could not read scheduler status: %s", exc)
        return {"running": False, "started_at": None, "last_run": {}, "errors": {}}
