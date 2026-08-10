"""
elimu_ai/health.py — Component health checks.

Key rule: Django being unavailable must NOT mark the AI worker as dead.
Each component is checked independently.
The Qdrant check verifies vector dimension == EMBED_DIM.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)
_START_TIME: float = time.monotonic()


def _probe(fn) -> Dict[str, Any]:
    t0 = time.monotonic()
    try:
        result = fn()
        result.setdefault("latency_ms", int((time.monotonic() - t0) * 1000))
        return result
    except Exception as exc:
        return {"status": "degraded", "detail": str(exc),
                "latency_ms": int((time.monotonic() - t0) * 1000)}


def check_gemini() -> Dict[str, Any]:
    from elimu_ai.config import GEMINI_API_KEY, LLM_MODEL
    if not GEMINI_API_KEY:
        return {"status": "degraded", "detail": "GEMINI_API_KEY not set"}
    from elimu_ai.gemini import _get_client
    client = _get_client()
    if client is None:
        return {"status": "degraded", "detail": "client init failed"}
    return {"status": "ok", "model": LLM_MODEL}


def check_qdrant() -> Dict[str, Any]:
    from elimu_ai.config import QDRANT_URL, COLLECTION_NAME, EMBED_DIM
    if not QDRANT_URL:
        return {"status": "degraded", "detail": "QDRANT_URL not set"}
    from elimu_ai.qdrant_db import _get_client, get_collection_info
    client = _get_client()
    if client is None:
        return {"status": "degraded", "detail": "client init failed"}
    info     = get_collection_info(COLLECTION_NAME)
    vec_size = info.get("vector_size")
    if vec_size is not None and vec_size != EMBED_DIM:
        return {
            "status":      "degraded",
            "detail":      f"Collection {COLLECTION_NAME} has {vec_size}-dim but EMBED_DIM={EMBED_DIM}",
            "vector_size": vec_size,
            "expected":    EMBED_DIM,
            "collection":  COLLECTION_NAME,
        }
    return {
        "status":       "ok",
        "collection":   COLLECTION_NAME,
        "vector_size":  vec_size,
        "points_count": info.get("points_count"),
        "col_status":   info.get("status"),
    }


def check_postgresql() -> Dict[str, Any]:
    from elimu_ai.config import DATABASE_URL
    if not DATABASE_URL:
        return {"status": "degraded", "detail": "DATABASE_URL not set"}
    from elimu_ai.db.connection import db_available
    if db_available():
        return {"status": "ok"}
    return {"status": "degraded", "detail": "connection pool unavailable"}


def check_catalog() -> Dict[str, Any]:
    from elimu_ai.catalog_search import catalog_available, _INDEX_PATH, _CATALOG_PATH
    if catalog_available():
        path = _INDEX_PATH if _INDEX_PATH.exists() else _CATALOG_PATH
        return {"status": "ok", "path": str(path)}
    return {"status": "degraded", "detail": "no catalog index on disk"}


def check_scheduler() -> Dict[str, Any]:
    from elimu_ai.scheduler import get_status  # lazy
    st = get_status()
    return {
        "status":      "ok" if st.get("running") else "degraded",
        "running":     st.get("running", False),
        "started_at":  st.get("started_at"),
        "error_count": len(st.get("errors", {})),
        "last_run":    {k: v.get("at") for k, v in st.get("last_run", {}).items()},
    }


def check_memory() -> Dict[str, Any]:
    from elimu_ai.memory import memory_store
    return {"status": "ok", "active_sessions": len(memory_store.session_ids())}


def check_agent_manager() -> Dict[str, Any]:
    from elimu_ai.agent_manager import get_status  # lazy
    st = get_status()
    return {
        "status":        "ok" if st.get("running") else "degraded",
        "running":       st.get("running", False),
        "jobs_launched": st.get("jobs_launched", 0),
        "last_check_at": st.get("last_check_at"),
        "django_status": st.get("django_status", "unknown"),
        "catalog_status":st.get("catalog_status", "unknown"),
    }


def check_django() -> Dict[str, Any]:
    """
    Check Django API reachability via HTTP.
    Django being unavailable must NOT affect the AI worker's own health status.
    """
    try:
        from elimu_ai.tools.forum import check_django_available
        ok = check_django_available()
        return {"status": "ok" if ok else "unavailable",
                "detail": None if ok else "Django API not reachable"}
    except Exception as exc:
        return {"status": "unavailable", "detail": str(exc)}


def check_tools() -> Dict[str, Any]:
    from elimu_ai.tool_registry import registry
    return {"status": "ok", "registered": registry.all_names(),
            "count": len(registry.all_names())}


def check_agents() -> Dict[str, Any]:
    try:
        from elimu_ai.agents.supervisor import SupervisorAgent  # noqa
        return {"status": "ok",
                "agents": ["supervisor","intent","planner","tool_selector","verifier","learning"]}
    except Exception as exc:
        return {"status": "degraded", "detail": str(exc)}


def check_personas() -> Dict[str, Any]:
    from elimu_ai.personas.registry import persona_registry
    names = persona_registry.all_names()
    return {"status": "ok", "personas": names, "count": len(names)}


def check_community() -> Dict[str, Any]:
    return check_django()


def check_forum() -> Dict[str, Any]:
    return check_django()


def check_recommendations() -> Dict[str, Any]:
    from elimu_ai.catalog_search import catalog_available
    ok = catalog_available()
    return {"status": "ok" if ok else "degraded", "catalog_available": ok}


def check_cache() -> Dict[str, Any]:
    from elimu_ai.db.connection import db_available
    db_ok = db_available()
    return {"status": "ok" if db_ok else "degraded",
            "backend": "postgresql" if db_ok else "none"}


def check_jobs() -> Dict[str, Any]:
    from elimu_ai.scheduler import get_status, _TASK_REGISTRY
    st = get_status()
    return {
        "status":     "ok" if st.get("running") else "degraded",
        "registered": [name for name, _, _ in _TASK_REGISTRY],
        "last_run":   st.get("last_run", {}),
        "errors":     st.get("errors", {}),
    }


def check_environment() -> Dict[str, Any]:
    required = ["GEMINI_API_KEY", "QDRANT_URL", "QDRANT_API_KEY",
                "COLLECTION_NAME", "ELIMU_API_BASE_URL", "AI_SHARED_SECRET"]
    optional = ["DATABASE_URL", "LOG_LEVEL", "LLM_MODEL", "EMBED_MODEL"]
    missing = [k for k in required if not os.getenv(k)]
    return {"status": "degraded" if missing else "ok",
            "missing_required": missing,
            "optional_set": [k for k in optional if os.getenv(k)]}


# ── Master report ─────────────────────────────────────────────────────────────

def get_health() -> Dict[str, Any]:
    from elimu_ai.config import SYSTEM_VERSION

    components = {
        "gemini":          _probe(check_gemini),
        "qdrant":          _probe(check_qdrant),
        "django":          _probe(check_django),     # independent — never kills AI status
        "postgresql":      _probe(check_postgresql),
        "catalog":         _probe(check_catalog),
        "scheduler":       _probe(check_scheduler),
        "memory":          _probe(check_memory),
        "agent_manager":   _probe(check_agent_manager),
        "tools":           _probe(check_tools),
        "agents":          _probe(check_agents),
        "personas":        _probe(check_personas),
        "community":       _probe(check_community),
        "forum":           _probe(check_forum),
        "recommendations": _probe(check_recommendations),
        "cache":           _probe(check_cache),
        "jobs":            _probe(check_jobs),
        "environment":     _probe(check_environment),
    }

    # AI worker is healthy if its OWN services are ok — not Django
    ai_critical = ("gemini", "qdrant", "catalog")
    ai_ok = all(components[k]["status"] == "ok" for k in ai_critical)

    return {
        "status":         "ok" if ai_ok else "degraded",
        "version":        SYSTEM_VERSION,
        "uptime_seconds": round(time.monotonic() - _START_TIME, 1),
        **components,
    }
