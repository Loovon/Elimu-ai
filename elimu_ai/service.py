"""
elimu_ai/service.py

FastAPI application — the only HTTP-facing layer.

Responsibilities:
  - Configure logging for the entire application.
  - Receive and validate HTTP requests.
  - Call run_agent().
  - Return structured JSON.

Endpoints:
  GET  /           → service info
  GET  /health     → liveness check
  POST /ask        → main chat endpoint  (primary)
  POST /chat       → alias for /ask      (backward compat)
  GET  /scheduler/status → background worker status

No business logic, no Gemini calls, no Qdrant calls live here.
"""

from __future__ import annotations

import logging
import logging.config
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from elimu_ai.agent import run_agent
from elimu_ai.config import LOG_LEVEL, SYSTEM_NAME, SYSTEM_VERSION

# ── Logging configuration ─────────────────────────────────────────────────────

logging.config.dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "root": {
        "level": LOG_LEVEL,
        "handlers": ["console"],
    },
})

logger = logging.getLogger(__name__)

# ── Scheduler state (shared with /scheduler/status) ──────────────────────────
# Populated by scheduler.py when it runs as a background thread.
scheduler_status: Dict[str, Any] = {
    "running": False,
    "started_at": None,
    "last_run": {},
}

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
    logger.error("Unhandled exception on %s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"success": False, "detail": "An internal error occurred. Please try again."},
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "status": "running",
        "service": SYSTEM_NAME,
        "version": SYSTEM_VERSION,
    }


@app.get("/health")
def health() -> Dict[str, str]:
    """Liveness probe — returns 200 OK if the service is up."""
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    """
    Primary chat endpoint.
    Accepts a message and optional conversation history.
    Returns the agent's response with persona, answer, sources, and tools used.
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
    return {
        "running":    scheduler_status["running"],
        "started_at": scheduler_status["started_at"],
        "last_run":   scheduler_status["last_run"],
    }
