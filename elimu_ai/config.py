"""
elimu_ai/config.py

Single source of truth for all configuration constants.
Reads from environment variables — raises clear errors on missing required keys.
"""

import os


def _require(name: str) -> str:
    """Return env var value or raise a descriptive error."""
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(
            f"Missing required environment variable: {name}. "
            f"Please set it before starting the service."
        )
    return value


def _optional(name: str, default: str = "") -> str:
    return os.getenv(name, default)


# ── Gemini ────────────────────────────────────────────────────────────────────
GEMINI_API_KEY: str = _optional("GEMINI_API_KEY")
LLM_MODEL: str = _optional("LLM_MODEL", "gemini-2.5-flash-lite")
EMBED_MODEL: str = _optional("EMBED_MODEL", "text-embedding-004")

# ── Qdrant ────────────────────────────────────────────────────────────────────
QDRANT_URL: str = _optional("QDRANT_URL")
QDRANT_API_KEY: str = _optional("QDRANT_API_KEY")
COLLECTION_NAME: str = _optional("COLLECTION_NAME", "elimu_library")

# ── Application ───────────────────────────────────────────────────────────────
SYSTEM_NAME: str = "Elimu AI"
REFERRAL_ID: str = _optional("REFERRAL_ID", "elm-elimutalks-1")
MAX_RESULTS: int = int(_optional("MAX_RESULTS", "5"))
