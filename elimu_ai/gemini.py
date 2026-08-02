"""
elimu_ai/gemini.py

Gemini client wrapper.
Responsibilities:
  - generate(prompt)  → call Gemini text generation
  - embed(text)       → call Gemini text-embedding-004

No business logic lives here.
"""

from __future__ import annotations

from elimu_ai.config import GEMINI_API_KEY, LLM_MODEL, EMBED_MODEL

try:
    from google import genai as _genai
    _client = _genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
except Exception:
    _client = None


def generate(prompt: str) -> str:
    """
    Send a prompt to Gemini and return the response text.
    Returns an error string (never raises) so callers can always display something.
    """
    if _client is None:
        return (
            "Elimu AI is temporarily unavailable. "
            "Please check that GEMINI_API_KEY is set and try again."
        )
    try:
        response = _client.models.generate_content(
            model=LLM_MODEL,
            contents=prompt,
        )
        return response.text or ""
    except Exception as exc:
        return f"Gemini error: {exc}"


def embed(text: str) -> list[float]:
    """
    Generate a Gemini text embedding for the given text.
    Returns an empty list on failure.
    """
    if _client is None:
        return []
    try:
        response = _client.models.embed_content(
            model=EMBED_MODEL,
            contents=text,
        )
        return response.embeddings[0].values
    except Exception:
        return []
