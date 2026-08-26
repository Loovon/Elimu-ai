"""
elimu_ai/config.py  —  Single source of truth for all configuration.
Auto-loads .env if python-dotenv is available.
"""

from __future__ import annotations

import os
import re


def parse_duration_seconds(value: object) -> int:
    """Parse human-friendly durations into canonical seconds.

    Accepts values like 12h, 2h, 30m, 3d, 45s, and plain numeric seconds.
    The config layer stores everything in seconds, while inputs can be written
    in human time units for easier tuning.
    """
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)

    text = str(value).strip().lower()
    if not text:
        return 0
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return int(float(text))

    match = re.fullmatch(
        r"(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>ms|msec|msecs|s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)",
        text,
    )
    if not match:
        raise ValueError(f"Unsupported duration value: {value!r}")

    num = float(match.group("num"))
    unit = match.group("unit")
    multipliers = {
        "ms": 0.001,
        "msec": 0.001,
        "msecs": 0.001,
        "s": 1,
        "sec": 1,
        "secs": 1,
        "second": 1,
        "seconds": 1,
        "m": 60,
        "min": 60,
        "mins": 60,
        "minute": 60,
        "minutes": 60,
        "h": 3600,
        "hr": 3600,
        "hrs": 3600,
        "hour": 3600,
        "hours": 3600,
        "d": 86400,
        "day": 86400,
        "days": 86400,
    }
    return int(round(num * multipliers[unit]))


# ── Auto-load .env ────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv()
except ImportError:
    pass  # dotenv optional — fall back to OS env vars

# ── Gemini ────────────────────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
LLM_MODEL: str      = os.getenv("LLM_MODEL", "gemini-3.6-flash")
EMBED_MODEL: str    = os.getenv("EMBED_MODEL", "gemini-embedding-001")
EMBED_DIM: int      = int(os.getenv("EMBED_DIM", "768"))   # canonical embedding dimension

# ── Qdrant ────────────────────────────────────────────────────────────────────
QDRANT_URL: str      = os.getenv("QDRANT_URL", "")
QDRANT_API_KEY: str  = os.getenv("QDRANT_API_KEY", "")
COLLECTION_NAME: str = os.getenv("COLLECTION_NAME", "elimu_library")
# Blue/green migration target — set to switch production collection
COLLECTION_NAME_V2: str = os.getenv("COLLECTION_NAME_V2", "elimu_library_v2")
# Minimum cosine similarity score for Qdrant results.
# Collection uses Cosine distance with L2-normalised 768-dim vectors,
# so scores are in [0, 1].  0.0 means no filtering (all results returned).
# Set via QDRANT_SCORE_THRESHOLD env var.  Start at 0.0 and tune upward
# after inspecting real score distributions from your collection.
QDRANT_SCORE_THRESHOLD: float = float(os.getenv("QDRANT_SCORE_THRESHOLD", "0.0"))

# ── Application ───────────────────────────────────────────────────────────────
SYSTEM_NAME: str    = "Elimu AI"
SYSTEM_VERSION: str = "2.2.0"
REFERRAL_ID: str    = os.getenv("REFERRAL_ID", "elm-elimutalks-1")
MAX_RESULTS: int    = int(os.getenv("MAX_RESULTS", "5"))
RAG_CANDIDATES: int = int(os.getenv("RAG_CANDIDATES", "30"))  # candidates before reranking

# ── Scheduler ─────────────────────────────────────────────────────────────────
SCHEDULER_ANSWER_INTERVAL: int    = parse_duration_seconds(os.getenv("SCHEDULER_ANSWER_INTERVAL", "1800"))
# generate_discussions: new proactive discussion every 4 hours
# (6 possible windows/day, guarded by MAX_PROACTIVE_DISCUSSIONS_PER_DAY=3)
SCHEDULER_DISCUSS_INTERVAL: int   = parse_duration_seconds(os.getenv("SCHEDULER_DISCUSS_INTERVAL", "4h"))
SCHEDULER_RECOMMEND_INTERVAL: int = parse_duration_seconds(os.getenv("SCHEDULER_RECOMMEND_INTERVAL", "1h"))
SCHEDULER_MODERATE_INTERVAL: int  = parse_duration_seconds(os.getenv("SCHEDULER_MODERATE_INTERVAL", "15m"))
SCHEDULER_CATALOG_INTERVAL: int   = parse_duration_seconds(os.getenv("SCHEDULER_CATALOG_INTERVAL", "12h"))
# How often to retry previously unanswered questions (default: 6 hours)
SCHEDULER_RETRY_FAILURES_INTERVAL: int = parse_duration_seconds(os.getenv("SCHEDULER_RETRY_FAILURES_INTERVAL", "6h"))
# Maximum number of retry attempts per failed query before giving up
MAX_RETRY_ATTEMPTS: int = int(os.getenv("MAX_RETRY_ATTEMPTS", "3"))

# ── Proactive community generation rate limits ────────────────────────────────
# Minimum seconds between proactive discussions (default: 4 hours — matches SCHEDULER_DISCUSS_INTERVAL)
PROACTIVE_DISCUSSION_COOLDOWN: int = parse_duration_seconds(os.getenv("PROACTIVE_DISCUSSION_COOLDOWN", "4h"))
# Maximum NEW proactive discussions per calendar day (3 = healthy volume without flooding)
MAX_PROACTIVE_DISCUSSIONS_PER_DAY: int = int(os.getenv("MAX_PROACTIVE_DISCUSSIONS_PER_DAY", "3"))
# Minimum seconds before the same persona posts again (1 hour — enables natural rotation
# across the community personas throughout the day)
PERSONA_COOLDOWN: int = parse_duration_seconds(os.getenv("PERSONA_COOLDOWN", "12h"))

# ── Thread growth / continuation ──────────────────────────────────────────────
# Target number of meaningful posts per discussion thread
THREAD_GROWTH_TARGET: int = int(os.getenv("THREAD_GROWTH_TARGET", "30"))
# Minimum posts before a thread is considered worth continuing (has existing engagement)
THREAD_MIN_POSTS_FOR_CONTINUATION: int = int(os.getenv("THREAD_MIN_POSTS_FOR_CONTINUATION", "2"))
# Minimum seconds between AI continuation posts in the SAME thread (3 hours)
# Prevents the scheduler from flooding a single thread back-to-back
THREAD_CONTINUATION_COOLDOWN: int = parse_duration_seconds(os.getenv("THREAD_CONTINUATION_COOLDOWN", "2h"))

# ── Article generation ────────────────────────────────────────────────────────
# How often to generate an article (every 12 hours = 2 articles/day max)
# How often the main parent/teacher/student persona rotation runs (every 45 min)
SCHEDULER_MAIN_PERSONA_INTERVAL: int = int(os.getenv("SCHEDULER_MAIN_PERSONA_INTERVAL", "2700"))

SCHEDULER_ARTICLE_INTERVAL: int = int(os.getenv("SCHEDULER_ARTICLE_INTERVAL", "43200"))
# Maximum articles per calendar day (2 = substantial but not overwhelming)
MAX_ARTICLES_PER_DAY: int = int(os.getenv("MAX_ARTICLES_PER_DAY", "2"))

# ── PostgreSQL ────────────────────────────────────────────────────────────────
DATABASE_URL: str = os.getenv("DATABASE_URL", "")

# ── Django API integration ────────────────────────────────────────────────────
ELIMU_API_BASE_URL: str = os.getenv("ELIMU_API_BASE_URL", "")
AI_SHARED_SECRET: str   = os.getenv("AI_SHARED_SECRET", "")

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
