#!/usr/bin/env python3
"""
ingest.py — Canonical Elimu Library ingestion pipeline.

Builds elimu_library_v2 (768-dim Cosine) from the richer catalogue.

Usage:
    python ingest.py [--dry-run] [--batch-size 50] [--collection elimu_library_v2]

Blue/green migration:
    1.  python ingest.py                   # builds elimu_library_v2
    2.  python ingest.py --validate        # verify collection
    3.  Set COLLECTION_NAME=elimu_library_v2 in .env and restart service
    4.  python ingest.py --delete-old      # ONLY after production switch, requires --confirm

Safety:
    - Never deletes elimu_library automatically.
    - Requires --delete-old + --confirm to remove any collection.
    - Idempotent: re-running the same data produces the same point IDs.
    - Duplicate URLs produce the same Qdrant point ID (deterministic hashing).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Load .env before anything else ───────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ingest")

# ── Constants ─────────────────────────────────────────────────────────────────
BASE_DIR          = Path(__file__).parent
CATALOGUE_FILE    = BASE_DIR / "elimu_catalogue.json"   # primary (richer)
CATALOG_FILE      = BASE_DIR / "elimu_catalog.json"     # secondary (fallback)
INDEX_FILE        = BASE_DIR / "elimu_index.json"

REF_SUFFIX = "?ref=elimutalks&return_url=https%3A%2F%2Felimitalks.com"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _deterministic_id(url: str) -> int:
    """Stable 63-bit integer ID from a document URL."""
    h = hashlib.sha256(url.encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big") & 0x7FFFFFFFFFFFFFFF


def _add_referral(url: str) -> str:
    if not url:
        return url
    if "ref=elimutalks" in url:
        return url
    sep = "&" if "?" in url else "?"
    return url + sep + "ref=elimutalks&return_url=https%3A%2F%2Felimitalks.com"


def _build_search_text(doc: Dict[str, Any]) -> str:
    """
    Build a rich searchable text from all semantic fields.
    Covers: grade + subject + term + year + curriculum + category +
            audience + doctype + description + title + keywords.
    """
    parts = []
    if doc.get("title"):
        parts.append(f"Title: {doc['title']}")
    if doc.get("description"):
        parts.append(f"Description: {doc['description']}")
    if doc.get("grade"):
        parts.append(f"Grade: {doc['grade']}")
    if doc.get("subject"):
        parts.append(f"Subject: {doc['subject']}")
    if doc.get("term"):
        parts.append(f"Term: {doc['term']}")
    if doc.get("year"):
        parts.append(f"Year: {doc['year']}")
    if doc.get("curriculum"):
        parts.append(f"Curriculum: {doc['curriculum']}")
    if doc.get("category"):
        parts.append(f"Category: {doc['category']}")
    if doc.get("audience"):
        parts.append(f"Audience: {doc['audience']}")
    if doc.get("doctype"):
        parts.append(f"Type: {doc['doctype']}")
    # Use _chroma_text if available (already rich)
    if doc.get("_chroma_text"):
        return doc["_chroma_text"]
    return "\n".join(parts)


def _build_payload(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Build the complete Qdrant point payload from a catalogue record."""
    url = doc.get("url", "") or ""
    referral = _add_referral(url)
    from datetime import datetime, timezone
    return {
        "source":       "elimu_catalogue",
        "source_file":  "elimu_catalogue.json",
        "source_type":  "catalog",           # trusted source — never AI-generated
        "ingested_at":  datetime.now(tz=timezone.utc).isoformat(),
        "title":        (doc.get("title") or "").strip(),
        "description":  (doc.get("description") or "").strip(),
        "url":          url,
        "referral_url": referral,
        "grade":        (doc.get("grade") or "").lower().strip(),
        "subject":      (doc.get("subject") or "").lower().strip(),
        "term":         str(doc.get("term") or "").strip(),
        "year":         str(doc.get("year") or "").strip(),
        "curriculum":   (doc.get("curriculum") or "").strip(),
        "category":     (doc.get("category") or "").strip(),
        "audience":     (doc.get("audience") or "").lower().strip(),
        "doctype":      (doc.get("doctype") or "").strip(),
        "price":        doc.get("price"),
        "text":         _build_search_text(doc),
    }


# ── Data loading ──────────────────────────────────────────────────────────────

def load_canonical_records() -> List[Dict[str, Any]]:
    """
    Load and deduplicate catalogue records.
    Primary: elimu_catalogue.json (richer, 12746 records)
    Secondary: elimu_catalog.json fills in any URLs not in primary
    Returns deduplicated list keyed by URL.
    """
    logger.info("Loading primary catalogue: %s", CATALOGUE_FILE)
    primary = json.loads(CATALOGUE_FILE.read_text(encoding="utf-8"))
    logger.info("  %d records in primary catalogue", len(primary))

    logger.info("Loading secondary catalog: %s", CATALOG_FILE)
    secondary = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    logger.info("  %d records in secondary catalog", len(secondary))

    # Deduplicate: primary wins on URL conflicts
    by_url: Dict[str, Dict[str, Any]] = {}
    skipped_no_url = 0

    for doc in primary:
        url = (doc.get("url") or "").strip()
        if not url:
            skipped_no_url += 1
            continue
        by_url[url] = doc

    for doc in secondary:
        url = (doc.get("url") or "").strip()
        if not url:
            continue
        if url not in by_url:
            by_url[url] = doc  # only add if not already from primary

    canonical = list(by_url.values())
    logger.info(
        "Canonical records: %d (skipped %d with no URL, %d secondary already in primary)",
        len(canonical),
        skipped_no_url,
        len(secondary) - (len(canonical) - sum(1 for d in primary if d.get("url"))),
    )
    return canonical


# ── Collection management ─────────────────────────────────────────────────────

def ensure_collection(client, collection: str, vec_size: int) -> None:
    from qdrant_client.models import VectorParams, Distance
    try:
        info = client.get_collection(collection)
        cfg = info.config.params.vectors
        existing_size = getattr(cfg, "size", None)
        if existing_size == vec_size:
            logger.info("Collection '%s' already exists (%d-dim). Will upsert.", collection, vec_size)
        else:
            raise ValueError(
                f"Collection '{collection}' exists with size {existing_size}, "
                f"but target is {vec_size}. Aborting."
            )
    except Exception as exc:
        if "Not found" in str(exc) or "doesn't exist" in str(exc).lower() or "404" in str(exc):
            logger.info("Creating collection '%s' (%d-dim Cosine).", collection, vec_size)
            client.create_collection(
                collection_name=collection,
                vectors_config=VectorParams(size=vec_size, distance=Distance.COSINE),
            )
        else:
            raise


# ── Ingestion ─────────────────────────────────────────────────────────────────

def run_ingest(
    collection: str,
    batch_size: int = 50,
    dry_run: bool = False,
    max_records: Optional[int] = None,
) -> int:
    from elimu_ai.config import QDRANT_URL, QDRANT_API_KEY, EMBED_DIM
    from elimu_ai.gemini import embed

    if not QDRANT_URL:
        logger.error("QDRANT_URL is not set. Check .env or environment variables.")
        sys.exit(1)

    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import PointStruct
    except ImportError:
        logger.error("qdrant-client not installed. Run: pip install qdrant-client")
        sys.exit(1)

    records = load_canonical_records()
    if max_records:
        records = records[:max_records]
        logger.info("Limiting to %d records (--max-records).", max_records)

    if dry_run:
        logger.info("[DRY RUN] Would ingest %d records into '%s'. Exiting.", len(records), collection)
        return 0

    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY or None)
    ensure_collection(client, collection, EMBED_DIM)

    total = len(records)
    upserted = 0
    skipped  = 0
    errors   = 0

    logger.info("Starting ingestion: %d records → '%s'", total, collection)

    for batch_start in range(0, total, batch_size):
        batch = records[batch_start:batch_start + batch_size]
        points = []

        for doc in batch:
            url = (doc.get("url") or "").strip()
            if not url:
                skipped += 1
                continue

            text = _build_search_text(doc)
            if not text.strip():
                skipped += 1
                continue

            vector = embed(text)
            if not vector or len(vector) != EMBED_DIM:
                logger.warning("Embedding failed for: %s", url[:80])
                errors += 1
                continue

            point_id = _deterministic_id(url)
            payload  = _build_payload(doc)

            points.append(PointStruct(id=point_id, vector=vector, payload=payload))

        if points:
            try:
                client.upsert(collection_name=collection, points=points)
                upserted += len(points)
            except Exception as exc:
                logger.error("Upsert batch failed: %s", exc)
                errors += len(points)

        done = min(batch_start + batch_size, total)
        logger.info("  Progress: %d/%d | upserted=%d skipped=%d errors=%d",
                    done, total, upserted, skipped, errors)

    logger.info(
        "Ingestion complete. upserted=%d skipped=%d errors=%d collection=%s",
        upserted, skipped, errors, collection,
    )
    return upserted


# ── Validation ────────────────────────────────────────────────────────────────

def validate_collection(collection: str) -> bool:
    from elimu_ai.config import QDRANT_URL, QDRANT_API_KEY, EMBED_DIM
    if not QDRANT_URL:
        logger.error("QDRANT_URL not set.")
        return False

    from qdrant_client import QdrantClient
    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY or None)

    try:
        info = client.get_collection(collection)
    except Exception as exc:
        logger.error("Collection '%s' not found: %s", collection, exc)
        return False

    cfg = info.config.params.vectors
    vec_size = getattr(cfg, "size", None)
    points   = info.points_count
    status   = str(info.status)

    logger.info("Collection: %s", collection)
    logger.info("  Vector size:  %s (expected %d) — %s",
                vec_size, EMBED_DIM, "OK" if vec_size == EMBED_DIM else "MISMATCH")
    logger.info("  Points:       %d", points or 0)
    logger.info("  Status:       %s", status)

    if vec_size != EMBED_DIM:
        logger.error("DIMENSION MISMATCH: collection has %d-dim, expected %d-dim.", vec_size, EMBED_DIM)
        return False
    if not points:
        logger.warning("Collection is empty.")
        return False

    # Quick semantic search test
    from elimu_ai.gemini import embed
    logger.info("Running test queries…")
    test_queries = [
        "Grade 4 Mathematics Term 2 notes",
        "Grade 6 Kiswahili notes",
        "CBC teacher schemes of work",
        "KCSE revision biology",
    ]
    for q in test_queries:
        vec = embed(q)
        if not vec:
            logger.error("Embedding failed for test query: %s", q)
            return False
        results = client.query_points(collection_name=collection, query=vec, limit=3)
        hits = results.points
        if hits:
            top = hits[0].payload or {}
            logger.info("  ✓ '%s' → '%s' (score=%.3f)", q[:40], top.get("title","?")[:50], hits[0].score)
        else:
            logger.warning("  ✗ '%s' → no results", q[:40])

    logger.info("Validation passed.")
    return True


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Elimu AI canonical ingestion pipeline")
    parser.add_argument("--collection", default="elimu_library_v2",
                        help="Target Qdrant collection (default: elimu_library_v2)")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--max-records", type=int, default=None,
                        help="Limit for testing (omit to ingest all)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Load and validate data without writing to Qdrant")
    parser.add_argument("--validate", action="store_true",
                        help="Validate an existing collection without ingesting")
    parser.add_argument("--delete-old", action="store_true",
                        help="Delete the OLD collection (requires --confirm)")
    parser.add_argument("--old-collection", default="elimu_library",
                        help="Name of old collection to delete (default: elimu_library)")
    parser.add_argument("--confirm", action="store_true",
                        help="Confirm destructive operations")
    args = parser.parse_args()

    if args.validate:
        ok = validate_collection(args.collection)
        sys.exit(0 if ok else 1)

    if args.delete_old:
        if not args.confirm:
            logger.error(
                "SAFETY: --delete-old requires --confirm. "
                "This would delete '%s'. Only run after production switch.", args.old_collection
            )
            sys.exit(1)
        from elimu_ai.config import QDRANT_URL, QDRANT_API_KEY
        from qdrant_client import QdrantClient
        client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY or None)
        logger.warning("Deleting collection '%s'…", args.old_collection)
        client.delete_collection(args.old_collection)
        logger.info("Deleted '%s'.", args.old_collection)
        return

    upserted = run_ingest(
        collection=args.collection,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        max_records=args.max_records,
    )

    if not args.dry_run and upserted > 0:
        logger.info("Running post-ingest validation…")
        validate_collection(args.collection)


if __name__ == "__main__":
    main()
