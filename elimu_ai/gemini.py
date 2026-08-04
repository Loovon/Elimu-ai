"""
elimu_ai/gemini.py

Single Gemini client for the entire application.
Responsibilities:
  - generate(prompt)  → text generation via Gemini
  - embed(text)       → text embedding via text-embedding-004

Rules:
  - One client instance, lazily initialised.
  - Missing API key returns a safe user-facing message — never raises.
  - Transient failures are retried up to 3 times with exponential backoff.
  - Raw API errors are never exposed to callers.
"""

from __future__ import annotations

import logging
import time
from typing import List

from elimu_ai.config import GEMINI_API_KEY, LLM_MODEL, EMBED_MODEL

logger = logging.getLogger(__name__)

# ── Client initialisation ─────────────────────────────────────────────────────

_client = None
_init_error: str = ""


def _get_client():
    """Lazy-initialise and return the Gemini client, or None on failure."""
    global _client, _init_error
    if _client is not None:
        return _client
    if not GEMINI_API_KEY:
        _init_error = "GEMINI_API_KEY environment variable is not set."
        logger.error("Gemini: %s", _init_error)
        return None
    try:
        from google import genai
        _client = genai.Client(api_key=GEMINI_API_KEY)
        logger.info("Gemini client initialised (model=%s).", LLM_MODEL)
        return _client
    except Exception as exc:
        _init_error = str(exc)
        logger.error("Gemini client init failed: %s", exc)
        return None


# ── Retry helper ──────────────────────────────────────────────────────────────

def _retry(fn, retries: int = 3, backoff: float = 1.5):
    """Call fn(); retry on exception up to `retries` times with backoff."""
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            wait = backoff ** attempt
            logger.warning(
                "Gemini attempt %d/%d failed: %s — retrying in %.1fs",
                attempt + 1, retries, exc, wait,
            )
            time.sleep(wait)
    raise last_exc  # type: ignore[misc]


# ── Public API ────────────────────────────────────────────────────────────────

def generate(prompt: str) -> str:
    """
    Generate a text response from Gemini.
    Never raises — returns a user-safe message on any failure.
    """
    client = _get_client()
    if client is None:
        return (
            "Elimu AI is temporarily unavailable. "
            "Please try again shortly or contact support."
        )
    try:
        def _call():
            response = client.models.generate_content(
                model=LLM_MODEL,
                contents=prompt,
            )
            return response.text or ""

        result = _retry(_call)
        logger.debug("Gemini generate: %d chars returned.", len(result))
        return result
    except Exception as exc:
        logger.error("Gemini generate failed after retries: %s", exc)
        return (
            "Elimu AI could not generate a response right now. "
            "Please try again in a moment."
        )


def embed(text: str) -> List[float]:
    """
    Generate a text embedding vector for the given text.
    Returns an empty list on any failure.
    """
    client = _get_client()
    if client is None:
        return []
    try:
        def _call():
            response = client.models.embed_content(
                model=EMBED_MODEL,
                contents=text,
            )
            return response.embeddings[0].values

        result = _retry(_call)
        return result
    except Exception as exc:
        logger.error("Gemini embed failed: %s", exc)
        return []
