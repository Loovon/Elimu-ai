"""
elimu_ai/config.py  —  Single source of truth for all configuration.
Auto-loads .env if python-dotenv is available.
"""

from __future__ import annotations

import os

# ── Auto-load .env ────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv()
except ImportError:
    pass  # dotenv optional — fall back to OS env vars

# ── Gemini ────────────────────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
LLM_MODEL: str      = os.getenv("LLM_MODEL", "gemini-2.5-flash")
EMBED_MODEL: str    = os.getenv("EMBED_MODEL", "gemini-embedding-001")
EMBED_DIM: int      = int(os.getenv("EMBED_DIM", "768"))   # canonical embedding dimension

# ── Qdrant ────────────────────────────────────────────────────────────────────
QDRANT_URL: str      = os.getenv("QDRANT_URL", "")
QDRANT_API_KEY: str  = os.getenv("QDRANT_API_KEY", "")
COLLECTION_NAME: str = os.getenv("COLLECTION_NAME", "elimu_library")
# Blue/green migration target — set to switch production collection
COLLECTION_NAME_V2: str = os.getenv("COLLECTION_NAME_V2", "elimu_library_v2")

# ── Application ───────────────────────────────────────────────────────────────
SYSTEM_NAME: str    = "Elimu AI"
SYSTEM_VERSION: str = "2.2.0"
REFERRAL_ID: str    = os.getenv("REFERRAL_ID", "elm-elimutalks-1")
MAX_RESULTS: int    = int(os.getenv("MAX_RESULTS", "5"))
RAG_CANDIDATES: int = int(os.getenv("RAG_CANDIDATES", "30"))  # candidates before reranking

# ── Scheduler ─────────────────────────────────────────────────────────────────
SCHEDULER_ANSWER_INTERVAL: int    = int(os.getenv("SCHEDULER_ANSWER_INTERVAL",    "1800"))
SCHEDULER_DISCUSS_INTERVAL: int   = int(os.getenv("SCHEDULER_DISCUSS_INTERVAL",   "86400"))
SCHEDULER_RECOMMEND_INTERVAL: int = int(os.getenv("SCHEDULER_RECOMMEND_INTERVAL", "3600"))
SCHEDULER_MODERATE_INTERVAL: int  = int(os.getenv("SCHEDULER_MODERATE_INTERVAL",  "900"))
SCHEDULER_CATALOG_INTERVAL: int   = int(os.getenv("SCHEDULER_CATALOG_INTERVAL",   "43200"))

# ── PostgreSQL ────────────────────────────────────────────────────────────────
DATABASE_URL: str = os.getenv("DATABASE_URL", "")

# ── Django API integration ────────────────────────────────────────────────────
ELIMU_API_BASE_URL: str = os.getenv("ELIMU_API_BASE_URL", "")
AI_SHARED_SECRET: str   = os.getenv("AI_SHARED_SECRET", "")

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
