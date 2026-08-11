"""
elimu_ai/qdrant_db.py

Qdrant vector store — single client for the entire application.

Functions:
  search(query, limit, filters)      → list of ScoredPoint
  search_structured(parsed_queries)  → merged list of ScoredPoint
  get_collection_info()              → dict with size / status / count
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from elimu_ai.config import (
    QDRANT_URL, QDRANT_API_KEY, COLLECTION_NAME,
    MAX_RESULTS, RAG_CANDIDATES, EMBED_DIM, QDRANT_SCORE_THRESHOLD,
)
from elimu_ai.gemini import embed as gemini_embed

logger = logging.getLogger(__name__)

_qdrant = None


def _get_client():
    global _qdrant
    if _qdrant is not None:
        return _qdrant
    if not QDRANT_URL:
        logger.warning("Qdrant: QDRANT_URL not set — vector search disabled.")
        return None
    try:
        from qdrant_client import QdrantClient
        _qdrant = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY or None)
        logger.info("Qdrant client initialised (collection=%s).", COLLECTION_NAME)
        return _qdrant
    except Exception as exc:
        logger.error("Qdrant client init failed: %s", exc)
        return None


def _build_filter(filters: Optional[Dict[str, Any]]) -> Optional[Any]:
    """Convert a plain dict of field→value into a Qdrant Filter object."""
    if not filters:
        return None
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        conditions = []
        for field, value in filters.items():
            if value:
                conditions.append(
                    FieldCondition(key=field, match=MatchValue(value=str(value).lower()))
                )
        if not conditions:
            return None
        return Filter(must=conditions)
    except Exception as exc:
        logger.warning("Qdrant: filter build failed: %s", exc)
        return None


def get_collection_info(collection: str = COLLECTION_NAME) -> Dict[str, Any]:
    """
    Return collection metadata.  Includes vector size and point count.
    Used by health checks to verify the collection has the correct dimension.
    """
    client = _get_client()
    if client is None:
        return {"status": "unavailable", "detail": "Qdrant client not initialised"}
    try:
        info = client.get_collection(collection)
        # qdrant-client ≥1.9: info.config.params.vectors is a VectorsConfig
        cfg = info.config.params.vectors
        # Flat (unnamed) collection: VectorParams directly
        if hasattr(cfg, "size"):
            vec_size = cfg.size
            distance = str(cfg.distance)
        else:
            # Named vectors: pick default
            vec_size = None
            distance = None
        return {
            "status":       str(info.status),
            "vector_size":  vec_size,
            "distance":     distance,
            "points_count": info.points_count,
            "expected_dim": EMBED_DIM,
            "dim_ok":       vec_size == EMBED_DIM if vec_size else None,
        }
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def search(
    query: str,
    limit: int = RAG_CANDIDATES,
    filters: Optional[Dict[str, Any]] = None,
    collection: str = COLLECTION_NAME,
    score_threshold: Optional[float] = None,
) -> List:
    """
    Embed the query and search Qdrant.

    Parameters
    ----------
    query    : text to embed and search
    limit    : maximum candidates to return (default = RAG_CANDIDATES for reranking)
    filters  : optional dict of payload field → value for metadata pre-filtering
    collection : collection name (default = COLLECTION_NAME from config)
    score_threshold : optional minimum cosine similarity score.  When None,
        falls back to QDRANT_SCORE_THRESHOLD from config (default 0.0 = no filter).
        Collection uses Cosine distance; Qdrant returns scores in [0, 1] for
        L2-normalised vectors.  Set via QDRANT_SCORE_THRESHOLD env var.
        Pass 0.0 explicitly to disable filtering for a specific call.
    """
    client = _get_client()
    if client is None:
        return []

    vector = gemini_embed(query)
    if not vector:
        logger.warning("Qdrant search: empty embedding — skipping.")
        return []

    if len(vector) != EMBED_DIM:
        logger.error(
            "Qdrant search: embedding dim %d ≠ expected %d — aborting search.",
            len(vector), EMBED_DIM,
        )
        return []

    qdrant_filter = _build_filter(filters)

    # Resolve effective threshold
    effective_threshold = score_threshold if score_threshold is not None else QDRANT_SCORE_THRESHOLD

    try:
        kwargs: Dict[str, Any] = dict(
            collection_name=collection,
            query=vector,
            limit=limit,
        )
        if qdrant_filter is not None:
            kwargs["query_filter"] = qdrant_filter
        if effective_threshold and effective_threshold > 0.0:
            kwargs["score_threshold"] = effective_threshold

        results = client.query_points(**kwargs)
        hits = results.points
        logger.debug("Qdrant search: %d hits for query=%r (threshold=%.3f)",
                     len(hits), query[:60], effective_threshold or 0.0)
        return hits
    except Exception as exc:
        logger.error("Qdrant search failed: %s", exc)
        return []


def search_structured(
    parsed_queries: List[Any],
    limit_per_query: int = 15,
    collection: str = COLLECTION_NAME,
) -> List[Dict[str, Any]]:
    """
    Execute multiple structured sub-queries independently and return merged
    deduplicated evidence records (as plain dicts with full payload).

    Each parsed_query must have: grade, subject, term, year, doc_type, audience.
    """
    from elimu_ai.catalog_search import search_catalog

    all_results: List[Dict[str, Any]] = []
    seen_urls: set = set()

    for sq in parsed_queries:
        grade    = getattr(sq, "grade", None)
        subject  = getattr(sq, "subject", None)
        term     = getattr(sq, "term", None)
        year     = getattr(sq, "year", None)
        doc_type = getattr(sq, "doc_type", None)
        audience = getattr(sq, "audience", None)
        original = getattr(sq, "original", "") or ""

        # 1. Try Qdrant semantic search with metadata filters
        filters = {}
        if grade:    filters["grade"]    = grade
        if subject:  filters["subject"]  = subject
        if term:     filters["term"]     = term
        if audience: filters["audience"] = audience

        search_text = " ".join(
            p for p in [grade, subject, f"Term {term}" if term else "", doc_type, original]
            if p
        ) or original

        hits = search(search_text, limit=limit_per_query, filters=filters, collection=collection)

        for hit in hits:
            p = hit.payload or {}
            url = p.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append({
                    "source":   "qdrant",
                    "score":    hit.score,
                    "grade":    p.get("grade", grade),
                    "subject":  p.get("subject", subject),
                    "term":     p.get("term", term),
                    "year":     p.get("year", year),
                    "title":    p.get("title", ""),
                    "url":      url,
                    "doctype":  p.get("doctype", doc_type),
                    "audience": p.get("audience", audience),
                    "price":    p.get("price"),
                    "description": p.get("description", ""),
                    "curriculum":  p.get("curriculum", ""),
                })

        # 2. Fall back to catalog flat-file search if Qdrant returns nothing
        if not hits:
            catalog_results = search_catalog(
                grade=grade, subject=subject, term=term, year=year,
                doctype=doc_type, audience=audience,
                keyword=original, max_results=limit_per_query,
            )
            for doc in catalog_results:
                url = doc.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_results.append({
                        "source":   "catalog",
                        "score":    0.0,
                        "grade":    doc.get("grade", ""),
                        "subject":  doc.get("subject", ""),
                        "term":     doc.get("term", ""),
                        "year":     doc.get("year", ""),
                        "title":    doc.get("title", ""),
                        "url":      url,
                        "doctype":  doc.get("doctype", ""),
                        "audience": doc.get("audience", ""),
                        "price":    doc.get("price"),
                        "description": doc.get("description", ""),
                        "curriculum":  doc.get("curriculum", ""),
                    })

    return all_results
