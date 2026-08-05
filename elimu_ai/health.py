"""
elimu_ai/health.py

Comprehensive health check system.

get_health() reports:
  - Gemini connectivity
  - Qdrant connectivity
  - PostgreSQL connectivity
  - Catalog availability
  - Scheduler status
  - Memory system status
  - Agent manager status
  - Environment variable presence
  - Service uptime
  - Version

Used by the /health endpoint in service.py.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Uptime tracking — set at module import time
_START_TIME: float = time.monotonic()


# ── Individual checks ─────────────────────────────────────────────────────────

def _check_gemini() -> Dict[str, Any]:
    from elimu_ai.config import GEMINI_API_KEY
    if not GEMINI_API_KEY:
        return {"status": "degraded", "detail": "GEMINI_API_KEY not set"}
    try:
        from elimu_ai.gemini import _get_client
        client = _get_client()
        if client is None:
            return {"status": "degraded", "detail": "Gemini client failed to initialise"}
        return {"status": "ok"}
    except Exception as exc:
        logger.warning("health: gemini check failed: %s", exc)
        return {"status": "degraded", "detail": str(exc)}


def _check_qdrant() -> Dict[str, Any]:
    from elimu_ai.config import QDRANT_URL
    if not QDRANT_URL:
        return {"status": "degraded", "detail": "QDRANT_URL not set"}
    try:
        from elimu_ai.qdrant_db import _get_client
        client = _get_client()
        if client is None:
            return {"status": "degraded", "detail": "Qdrant client failed to initialise"}
        return {"status": "ok"}
    except Exception as exc:
        logger.warning("health: qdrant check failed: %s", exc)
        return {"status": "degraded", "detail": str(exc)}


def _check_postgresql() -> Dict[str, Any]:
    from elimu_ai.config import DATABASE_URL
    if not DATABASE_URL:
        return {"status": "degraded", "detail": "DATABASE_URL not set"}
    try:
        from elimu_ai.db.connection import db_available
        if db_available():
            return {"status": "ok"}
        return {"status": "degraded", "detail": "Connection pool unavailable"}
    except Exception as exc:
        logger.warning("health: postgresql check failed: %s", exc)
        return {"status": "degraded", "detail": str(exc)}


def _check_catalog() -> Dict[str, Any]:
    try:
        from elimu_ai.catalog_search import catalog_available, _INDEX_PATH, _CATALOG_PATH
        if catalog_available():
            path = _INDEX_PATH if _INDEX_PATH.exists() else _CATALOG_PATH
            return {"status": "ok", "path": str(path)}
        return {"status": "degraded", "detail": "No catalog index found on disk"}
    except Exception as exc:
        logger.warning("health: catalog check failed: %s", exc)
        return {"status": "degraded", "detail": str(exc)}


def _check_scheduler() -> Dict[str, Any]:
    try:
        from elimu_ai.scheduler import get_status
        st = get_status()
        running = st.get("running", False)
        errors  = st.get("errors", {})
        return {
            "status":     "ok" if running else "degraded",
            "running":    running,
            "started_at": st.get("started_at"),
            "errors":     len(errors),
            "last_run":   {k: v.get("at") for k, v in st.get("last_run", {}).items()},
        }
    except Exception as exc:
        logger.warning("health: scheduler check failed: %s", exc)
        return {"status": "degraded", "detail": str(exc)}


def _check_memory() -> Dict[str, Any]:
    try:
        from elimu_ai.memory import memory_store
        sessions = len(memory_store.session_ids())
        return {"status": "ok", "active_sessions": sessions}
    except Exception as exc:
        logger.warning("health: memory check failed: %s", exc)
        return {"status": "degraded", "detail": str(exc)}


def _check_agent_manager() -> Dict[str, Any]:
    try:
        from elimu_ai.agent_manager import get_status
        st = get_status()
        return {
            "status":       "ok" if st.get("running") else "degraded",
            "running":      st.get("running", False),
            "started_at":   st.get("started_at"),
            "jobs_launched":st.get("jobs_launched", 0),
            "last_check_at":st.get("last_check_at"),
        }
    except Exception as exc:
        logger.warning("health: agent_manager check failed: %s", exc)
        return {"status": "degraded", "detail": str(exc)}


def _check_environment() -> Dict[str, Any]:
    """Report which required environment variables are set (not their values)."""
    required = [
        "GEMINI_API_KEY", "QDRANT_URL", "QDRANT_API_KEY",
        "COLLECTION_NAME", "DATABASE_URL",
        "ELIMU_API_BASE_URL", "AI_SHARED_SECRET",
    ]
    optional = ["LOG_LEVEL", "LLM_MODEL", "EMBED_MODEL", "REFERRAL_ID", "MAX_RESULTS"]

    missing_required = [k for k in required if not os.getenv(k)]
    present_optional = [k for k in optional if os.getenv(k)]

    return {
        "status":          "degraded" if missing_required else "ok",
        "missing_required": missing_required,
        "optional_set":    present_optional,
    }


# ── Master health report ──────────────────────────────────────────────────────

def get_health() -> Dict[str, Any]:
    """
    Return a full health report for all platform components.

    Shape:
        status          : "ok" | "degraded"
        version         : str
        uptime_seconds  : float
        gemini          : {...}
        qdrant          : {...}
        postgresql      : {...}
        catalog         : {...}
        scheduler       : {...}
        memory          : {...}
        agent_manager   : {...}
        environment     : {...}
    """
    from elimu_ai.config import SYSTEM_VERSION

    gemini         = _check_gemini()
    qdrant         = _check_qdrant()
    postgresql     = _check_postgresql()
    catalog        = _check_catalog()
    scheduler      = _check_scheduler()
    memory         = _check_memory()
    agent_manager  = _check_agent_manager()
    environment    = _check_environment()

    # Overall status: degraded if any critical component is degraded
    critical = (gemini, qdrant, catalog)
    overall  = "ok" if all(c["status"] == "ok" for c in critical) else "degraded"

    return {
        "status":         overall,
        "version":        SYSTEM_VERSION,
        "uptime_seconds": round(time.monotonic() - _START_TIME, 1),
        "gemini":         gemini,
        "qdrant":         qdrant,
        "postgresql":     postgresql,
        "catalog":        catalog,
        "scheduler":      scheduler,
        "memory":         memory,
        "agent_manager":  agent_manager,
        "environment":    environment,
    }
