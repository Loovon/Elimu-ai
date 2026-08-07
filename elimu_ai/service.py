"""
elimu_ai/service.py  —  FastAPI application, sole HTTP-facing layer.
All existing endpoints preserved. Granular /health/* endpoints added.
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

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title=SYSTEM_NAME,
    description="Autonomous educational AI — ElimuTalks & Elimu Library.",
    version=SYSTEM_VERSION,
)


# ── Schemas ───────────────────────────────────────────────────────────────────

class AskRequest(BaseModel):
    message:    str = Field(..., min_length=1, max_length=2000)
    history:    List[Dict[str, str]] = Field(default_factory=list)
    session_id: Optional[str] = None
    user_id:    Optional[int] = None


class AskResponse(BaseModel):
    success: bool
    persona: str
    answer:  str
    sources: List[str]
    tools:   List[str]


# ── Exception handler ─────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def _global_exc(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled on %s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"success": False, "detail": "An internal error occurred."},
    )


# ── Core routes (ALL PRESERVED) ───────────────────────────────────────────────

@app.get("/")
def root() -> Dict[str, Any]:
    return {"status": "running", "service": SYSTEM_NAME, "version": SYSTEM_VERSION}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    request_id = str(uuid.uuid4())
    t0 = time.monotonic()
    logger.info("POST /ask rid=%s user=%s msg=%r", request_id[:8], req.user_id, req.message[:80])
    try:
        result = run_agent(
            question=req.message,
            history=req.history,
            session_id=req.session_id or request_id,
            user_id=req.user_id,
            request_id=request_id,
        )
        logger.info("POST /ask rid=%s persona=%s ms=%d",
                    request_id[:8], result["persona"],
                    int((time.monotonic()-t0)*1000))
        return AskResponse(success=True, **result)
    except Exception as exc:
        logger.error("POST /ask rid=%s failed: %s", request_id[:8], exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Agent error — please try again.")


@app.post("/chat", response_model=AskResponse, include_in_schema=False)
def chat(req: AskRequest) -> AskResponse:
    return ask(req)


@app.get("/scheduler/status")
def get_scheduler_status() -> Dict[str, Any]:
    try:
        from elimu_ai.scheduler import get_status
        return get_status()
    except Exception as exc:
        logger.warning("scheduler status: %s", exc)
        return {"running": False, "started_at": None, "last_run": {}, "errors": {}}


# ── Health routes ─────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> Dict[str, Any]:
    from elimu_ai.health import get_health
    return get_health()


@app.get("/health/gemini")
def health_gemini() -> Dict[str, Any]:
    from elimu_ai.health import check_gemini, _probe
    return _probe(check_gemini)


@app.get("/health/qdrant")
def health_qdrant() -> Dict[str, Any]:
    from elimu_ai.health import check_qdrant, _probe
    return _probe(check_qdrant)


@app.get("/health/database")
def health_database() -> Dict[str, Any]:
    from elimu_ai.health import check_postgresql, _probe
    return _probe(check_postgresql)


@app.get("/health/catalog")
def health_catalog() -> Dict[str, Any]:
    from elimu_ai.health import check_catalog, _probe
    return _probe(check_catalog)


@app.get("/health/scheduler")
def health_scheduler() -> Dict[str, Any]:
    from elimu_ai.health import check_scheduler, _probe
    return _probe(check_scheduler)


@app.get("/health/memory")
def health_memory() -> Dict[str, Any]:
    from elimu_ai.health import check_memory, _probe
    return _probe(check_memory)


@app.get("/health/tools")
def health_tools() -> Dict[str, Any]:
    from elimu_ai.health import check_tools, _probe
    return _probe(check_tools)


@app.get("/health/agents")
def health_agents() -> Dict[str, Any]:
    from elimu_ai.health import check_agents, _probe
    return _probe(check_agents)


@app.get("/health/jobs")
def health_jobs() -> Dict[str, Any]:
    from elimu_ai.health import check_jobs, _probe
    return _probe(check_jobs)


@app.get("/health/cache")
def health_cache() -> Dict[str, Any]:
    from elimu_ai.health import check_cache, _probe
    return _probe(check_cache)


@app.get("/health/recommendations")
def health_recommendations() -> Dict[str, Any]:
    from elimu_ai.health import check_recommendations, _probe
    return _probe(check_recommendations)


@app.get("/health/community")
def health_community() -> Dict[str, Any]:
    from elimu_ai.health import check_community, _probe
    return _probe(check_community)


@app.get("/health/forum")
def health_forum() -> Dict[str, Any]:
    from elimu_ai.health import check_forum, _probe
    return _probe(check_forum)


@app.get("/health/personas")
def health_personas() -> Dict[str, Any]:
    from elimu_ai.health import check_personas, _probe
    return _probe(check_personas)
