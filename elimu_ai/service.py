"""
elimu_ai/service.py

FastAPI application — the sole HTTP-facing layer.

Responsibilities:
  - Configure logging.
  - Validate and authenticate requests.
  - Assign request IDs for tracing.
  - Call run_agent() / orchestrator.
  - Return structured JSON.
  - Expose health, scheduler, and agent manager status endpoints.

Endpoints (ALL PRESERVED — no renames):
  GET  /                  → service info
  GET  /health            → full dependency health report
  POST /ask               → primary chat endpoint
  POST /chat              → backward-compat alias for /ask
  GET  /scheduler/status  → APScheduler status

No business logic. No Gemini calls. No Qdrant calls.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

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
    description="Autonomous educational AI — ElimuTalks & Elimu Library.",
    version=SYSTEM_VERSION,
)


# ── Schemas (UNCHANGED — API contract preserved) ──────────────────────────────

class AskRequest(BaseModel):
    message:    str = Field(..., min_length=1, max_length=2000)
    history:    List[Dict[str, str]] = Field(default_factory=list)
    session_id: Optional[str] = Field(default=None, description="Optional session identifier")
    user_id:    Optional[int] = Field(default=None, description="Optional authenticated user ID")


class AskResponse(BaseModel):
    success: bool
    persona: str
    answer:  str
    sources: List[str]
    tools:   List[str]


# ── Exception handler ─────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled exception on %s: %s", request.url.path, exc, exc_info=True
    )
    return JSONResponse(
        status_code=500,
        content={"success": False, "detail": "An internal error occurred. Please try again."},
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
    """Full dependency health report (Gemini, Qdrant, PostgreSQL, Scheduler…)."""
    from elimu_ai.health import get_health
    return get_health()


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    """
    Primary chat endpoint.
    Accepts a message and optional conversation history.
    Returns persona, answer, sources, and tools used.
    """
    request_id = str(uuid.uuid4())
    t_start    = time.monotonic()

    logger.info(
        "POST /ask request_id=%s user_id=%s session=%s message=%r",
        request_id[:8], req.user_id, req.session_id, req.message[:80],
    )

    try:
        result = run_agent(
            question=req.message,
            history=req.history,
            session_id=req.session_id or request_id,
            user_id=req.user_id,
            request_id=request_id,
        )
        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        logger.info(
            "POST /ask request_id=%s persona=%s tools=%s ms=%d",
            request_id[:8], result["persona"], result["tools"], elapsed_ms,
        )
        return AskResponse(
            success=True,
            persona=result["persona"],
            answer=result["answer"],
            sources=result["sources"],
            tools=result["tools"],
        )
    except Exception as exc:
        logger.error(
            "POST /ask request_id=%s failed: %s", request_id[:8], exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail="Agent error — please try again.")


@app.post("/chat", response_model=AskResponse, include_in_schema=False)
def chat(req: AskRequest) -> AskResponse:
    """Backward-compatible alias for /ask."""
    return ask(req)


@app.get("/scheduler/status")
def get_scheduler_status() -> Dict[str, Any]:
    """Return current APScheduler status."""
    try:
        from elimu_ai.scheduler import get_status
        return get_status()
    except Exception as exc:
        logger.warning("Could not read scheduler status: %s", exc)
        return {"running": False, "started_at": None, "last_run": {}, "errors": {}}
