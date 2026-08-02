"""
elimu_ai/qdrant_db.py

Qdrant vector store client.
Responsibilities:
  - embed(text)         → delegate to gemini.embed()
  - search(query, n)    → embed then query Qdrant, return ScoredPoint list

No business logic.  No Gemini generation.
"""

from __future__ import annotations

from typing import List

from elimu_ai.config import QDRANT_URL, QDRANT_API_KEY, COLLECTION_NAME, MAX_RESULTS
from elimu_ai.gemini import embed as gemini_embed

_qdrant = None


def _get_client():
    """Lazy-initialise the Qdrant client so import never crashes."""
    global _qdrant
    if _qdrant is not None:
        return _qdrant
    if not QDRANT_URL:
        return None
    try:
        from qdrant_client import QdrantClient
        _qdrant = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY or None)
        return _qdrant
    except Exception:
        return None


def search(query: str, limit: int = MAX_RESULTS) -> List:
    """
    Embed the query and search Qdrant.
    Returns a list of ScoredPoint objects, or [] on any error.
    """
    client = _get_client()
    if client is None:
        return []

    vector = gemini_embed(query)
    if not vector:
        return []

    try:
        results = client.query_points(
            collection_name=COLLECTION_NAME,
            query=vector,
            limit=limit,
        )
        return results.points
    except Exception:
        return []
