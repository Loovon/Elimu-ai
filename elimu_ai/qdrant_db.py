"""
elimu_ai/qdrant_db.py

Qdrant vector store — single client for the entire application.
Responsibilities:
  - search(query, limit) → list of ScoredPoint

Rules:
  - One Qdrant client instance, lazily initialised.
  - Delegates embedding to gemini.embed().
  - Returns [] on any failure — never raises.
"""

from __future__ import annotations

import logging
from typing import List

from elimu_ai.config import QDRANT_URL, QDRANT_API_KEY, COLLECTION_NAME, MAX_RESULTS
from elimu_ai.gemini import embed as gemini_embed

logger = logging.getLogger(__name__)

_qdrant = None


def _get_client():
    """Lazy-initialise the Qdrant client."""
    global _qdrant
    if _qdrant is not None:
        return _qdrant
    if not QDRANT_URL:
        logger.warning("Qdrant: QDRANT_URL is not set — vector search disabled.")
        return None
    try:
        from qdrant_client import QdrantClient
        _qdrant = QdrantClient(
            url=QDRANT_URL,
            api_key=QDRANT_API_KEY or None,
        )
        logger.info("Qdrant client initialised (url=%s, collection=%s).", QDRANT_URL, COLLECTION_NAME)
        return _qdrant
    except Exception as exc:
        logger.error("Qdrant client init failed: %s", exc)
        return None


def search(query: str, limit: int = MAX_RESULTS) -> List:
    """
    Embed the query and search Qdrant for semantically similar documents.
    Returns a list of ScoredPoint objects, or [] on any error.
    """
    client = _get_client()
    if client is None:
        return []

    vector = gemini_embed(query)
    if not vector:
        logger.warning("Qdrant search: embedding returned empty — skipping search.")
        return []

    try:
        results = client.query_points(
            collection_name=COLLECTION_NAME,
            query=vector,
            limit=limit,
        )
        hits = results.points
        logger.debug("Qdrant search: %d hits for query=%r", len(hits), query[:60])
        return hits
    except Exception as exc:
        logger.error("Qdrant search failed: %s", exc)
        return []
