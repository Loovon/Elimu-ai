"""
elimu_ai/gemini.py

Single Gemini client.  embed() always returns exactly EMBED_DIM (768) floats.

Critical rules:
  - EMBED_DIM is read from config — never hard-coded.
  - output_dimensionality is explicitly passed to the API.
  - The resulting vector is L2-normalised before returning.
  - If the returned vector ≠ EMBED_DIM the function logs an error and returns [].
  - Query and document embeddings go through identical code paths.
"""

from __future__ import annotations

import logging
import math
import time
from typing import List

from elimu_ai.config import GEMINI_API_KEY, LLM_MODEL, EMBED_MODEL, EMBED_DIM

logger = logging.getLogger(__name__)

# ── Client initialisation ─────────────────────────────────────────────────────

_client = None
_init_error: str = ""


def _get_client():
    global _client, _init_error
    if _client is not None:
        return _client
    if not GEMINI_API_KEY:
        _init_error = "GEMINI_API_KEY not set."
        logger.error("Gemini: %s", _init_error)
        return None
    try:
        from google import genai
        _client = genai.Client(api_key=GEMINI_API_KEY)
        logger.info("Gemini client initialised (model=%s, embed_model=%s, embed_dim=%d).",
                    LLM_MODEL, EMBED_MODEL, EMBED_DIM)
        return _client
    except Exception as exc:
        _init_error = str(exc)
        logger.error("Gemini client init failed: %s", exc)
        return None


# ── Normalisation ─────────────────────────────────────────────────────────────

def _l2_normalize(vec: List[float]) -> List[float]:
    """L2-normalise a float vector in-place (returns new list)."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return vec
    return [x / norm for x in vec]


# ── Retry helper ──────────────────────────────────────────────────────────────

def _retry(fn, retries: int = 3, backoff: float = 1.5):
    last_exc = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            wait = backoff ** attempt
            logger.warning("Gemini attempt %d/%d failed: %s — retry in %.1fs",
                           attempt + 1, retries, exc, wait)
            time.sleep(wait)
    raise last_exc


# ── Public API ────────────────────────────────────────────────────────────────

def generate(prompt: str) -> str:
    """
    Generate a text response from Gemini.
    Never raises — returns a user-safe message on failure.
    """
    client = _get_client()
    if client is None:
        return ("Elimu AI is temporarily unavailable. "
                "Please try again shortly or contact support.")
    try:
        result = _retry(lambda: client.models.generate_content(
            model=LLM_MODEL, contents=prompt,
        ).text or "")
        logger.debug("Gemini generate: %d chars.", len(result))
        return result
    except Exception as exc:
        logger.error("Gemini generate failed: %s", exc)
        return ("Elimu AI could not generate a response right now. "
                "Please try again in a moment.")


def embed(text: str) -> List[float]:
    """
    Generate a text embedding of exactly EMBED_DIM dimensions.

    Process:
      1. Call Gemini with output_dimensionality=EMBED_DIM
      2. Validate returned length == EMBED_DIM
      3. L2-normalise the vector
      4. Return the normalised vector, or [] on any failure

    Query and document embeddings are identical in process — no divergence.
    """
    client = _get_client()
    if client is None:
        return []
    try:
        from google.genai import types as _types

        def _call():
            resp = client.models.embed_content(
                model=EMBED_MODEL,
                contents=text,
                config=_types.EmbedContentConfig(
                    output_dimensionality=EMBED_DIM,
                ),
            )
            return resp.embeddings[0].values

        raw = _retry(_call)

        if len(raw) != EMBED_DIM:
            logger.error(
                "Gemini embed: dimension mismatch — expected %d, got %d. "
                "Check EMBED_MODEL and EMBED_DIM configuration.",
                EMBED_DIM, len(raw),
            )
            return []

        normalised = _l2_normalize(list(raw))
        logger.debug("Gemini embed: %d-dim vector (normalised).", EMBED_DIM)
        return normalised

    except Exception as exc:
        logger.error("Gemini embed failed: %s", exc)
        return []
