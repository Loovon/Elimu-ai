"""
elimu_ai/exceptions.py

Custom exception hierarchy for Elimu AI.

All application-level errors descend from ElimuAIError so callers
can catch the whole family with a single except clause.

Usage:
    from elimu_ai.exceptions import GeminiUnavailableError, CatalogError
    raise GeminiUnavailableError("API key not set")
"""

from __future__ import annotations


# ── Base ──────────────────────────────────────────────────────────────────────

class ElimuAIError(Exception):
    """Base class for all Elimu AI application errors."""


# ── Configuration ─────────────────────────────────────────────────────────────

class ConfigurationError(ElimuAIError):
    """A required environment variable or configuration value is missing."""


# ── Gemini ────────────────────────────────────────────────────────────────────

class GeminiError(ElimuAIError):
    """Base class for Gemini-related errors."""


class GeminiUnavailableError(GeminiError):
    """Gemini client could not be initialised (missing key, network issue)."""


class GeminiGenerationError(GeminiError):
    """Gemini generation request failed after all retries."""


class GeminiEmbedError(GeminiError):
    """Gemini embedding request failed."""


# ── Qdrant ────────────────────────────────────────────────────────────────────

class QdrantError(ElimuAIError):
    """Base class for Qdrant-related errors."""


class QdrantUnavailableError(QdrantError):
    """Qdrant client could not be initialised (missing URL, network issue)."""


class QdrantSearchError(QdrantError):
    """Qdrant search query failed."""


# ── Catalog ───────────────────────────────────────────────────────────────────

class CatalogError(ElimuAIError):
    """Base class for catalog-related errors."""


class CatalogNotFoundError(CatalogError):
    """The catalog index file does not exist on disk."""


class CatalogParseError(CatalogError):
    """The catalog index file could not be parsed."""


# ── HTTP Client ───────────────────────────────────────────────────────────────

class HTTPClientError(ElimuAIError):
    """Base class for HTTP client errors when calling the Django API."""


class AuthenticationError(HTTPClientError):
    """Request was rejected due to invalid or missing credentials."""


class HTTPTimeoutError(HTTPClientError):
    """Request to the Django API timed out."""


class HTTPResponseError(HTTPClientError):
    """Django API returned an unexpected HTTP status code."""

    def __init__(self, message: str, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code


# ── Agent ─────────────────────────────────────────────────────────────────────

class AgentError(ElimuAIError):
    """Unexpected error in the agent orchestration pipeline."""


# ── Scheduler ─────────────────────────────────────────────────────────────────

class SchedulerError(ElimuAIError):
    """Error in the background scheduler."""
