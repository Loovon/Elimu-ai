"""
elimu_ai/health.py

Health check utilities.

Provides get_health() which reports the status of each external dependency
(Gemini, Qdrant, Catalog) without raising exceptions.

Used by the /health endpoint in service.py.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _check_gemini() -> Dict[str, Any]:
    """Return Gemini connectivity status."""
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
    """Return Qdrant connectivity status."""
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


def _check_catalog() -> Dict[str, Any]:
    """Return catalog availability status."""
    try:
        from elimu_ai.catalog_search import catalog_available, _INDEX_PATH, _CATALOG_PATH
        if catalog_available():
            path = _INDEX_PATH if _INDEX_PATH.exists() else _CATALOG_PATH
            return {"status": "ok", "path": str(path)}
        return {"status": "degraded", "detail": "No catalog index found on disk"}
    except Exception as exc:
        logger.warning("health: catalog check failed: %s", exc)
        return {"status": "degraded", "detail": str(exc)}


def get_health() -> Dict[str, Any]:
    """
    Return a health report for all external dependencies.

    Returns
    -------
    dict:
        status  : "ok" | "degraded"
        gemini  : sub-status dict
        qdrant  : sub-status dict
        catalog : sub-status dict
    """
    gemini  = _check_gemini()
    qdrant  = _check_qdrant()
    catalog = _check_catalog()

    all_ok = all(
        s["status"] == "ok"
        for s in (gemini, qdrant, catalog)
    )

    return {
        "status":  "ok" if all_ok else "degraded",
        "gemini":  gemini,
        "qdrant":  qdrant,
        "catalog": catalog,
    }
