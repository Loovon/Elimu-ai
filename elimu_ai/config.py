"""
elimu_ai/config.py

Single source of truth for all configuration constants.
Reads from environment variables. Optional vars get safe defaults.
Required vars (GEMINI_API_KEY) are validated at call time in gemini.py,
not at import time, so the service can start and report the error cleanly.
"""

from __future__ import annotations

import os

# ── Gemini ────────────────────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
LLM_MODEL: str      = os.getenv("LLM_MODEL", "gemini-2.5-flash")
EMBED_MODEL: str    = os.getenv("EMBED_MODEL", "text-embedding-004")

# ── Qdrant ────────────────────────────────────────────────────────────────────
QDRANT_URL: str     = os.getenv("QDRANT_URL", "")
QDRANT_API_KEY: str = os.getenv("QDRANT_API_KEY", "")
COLLECTION_NAME: str = os.getenv("COLLECTION_NAME", "elimu_library")

# ── Application ───────────────────────────────────────────────────────────────
SYSTEM_NAME: str  = "Elimu AI"
SYSTEM_VERSION: str = "2.1.0"
REFERRAL_ID: str  = os.getenv("REFERRAL_ID", "elm-elimutalks-1")
MAX_RESULTS: int  = int(os.getenv("MAX_RESULTS", "5"))

# ── Scheduler ─────────────────────────────────────────────────────────────────
# How often each background task runs, in seconds.
SCHEDULER_ANSWER_INTERVAL: int    = int(os.getenv("SCHEDULER_ANSWER_INTERVAL",    "1800"))   # 30 min
SCHEDULER_DISCUSS_INTERVAL: int   = int(os.getenv("SCHEDULER_DISCUSS_INTERVAL",   "86400"))  # 24 hr
SCHEDULER_RECOMMEND_INTERVAL: int = int(os.getenv("SCHEDULER_RECOMMEND_INTERVAL", "3600"))   # 1 hr
SCHEDULER_MODERATE_INTERVAL: int  = int(os.getenv("SCHEDULER_MODERATE_INTERVAL",  "900"))    # 15 min
SCHEDULER_CATALOG_INTERVAL: int   = int(os.getenv("SCHEDULER_CATALOG_INTERVAL",   "43200"))  # 12 hr

# ── Django API integration ────────────────────────────────────────────────────
# Base URL of the ElimuTalks Django REST API.
# Used by http_client.py for all outbound requests.
ELIMU_API_BASE_URL: str = os.getenv("ELIMU_API_BASE_URL", "")

# Shared secret for AI ↔ Django authentication.
# Every outbound request carries:  Authorization: Bearer <AI_SHARED_SECRET>
AI_SHARED_SECRET: str = os.getenv("AI_SHARED_SECRET", "")

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
