"""
elimu_ai/http_client.py

Authenticated HTTP client for communicating with the ElimuTalks Django API.

Responsibilities:
  - Authenticated requests (Bearer AI_SHARED_SECRET)
  - Retries with exponential backoff
  - Configurable timeouts
  - Structured error handling
  - Request / response logging

Rules:
  - No business logic.
  - No Django ORM.
  - No Gemini calls.
  - Never hardcode secrets — credentials come from config.py only.

Assumed Django API endpoints:
  POST /api/ai/chat/
  POST /api/ai/tasks/
  GET  /api/ai/results/{task_id}/
  GET  /api/ai/health/

Usage:
    from elimu_ai.http_client import ElimuAPIClient
    client = ElimuAPIClient()
    response = client.post("/api/ai/chat/", {"message": "hello"})
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from elimu_ai.config import AI_SHARED_SECRET, ELIMU_API_BASE_URL
from elimu_ai.exceptions import (
    AuthenticationError,
    HTTPClientError,
    HTTPResponseError,
    HTTPTimeoutError,
)

logger = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────────

_DEFAULT_TIMEOUT  = 15.0   # seconds per request
_DEFAULT_RETRIES  = 3
_DEFAULT_BACKOFF  = 1.5    # seconds; multiplied by attempt index


class ElimuAPIClient:
    """
    Authenticated HTTP client for the ElimuTalks Django REST API.

    All requests automatically include:
        Authorization: Bearer <AI_SHARED_SECRET>
        Content-Type: application/json
        Accept: application/json

    Parameters
    ----------
    base_url : str, optional
        Override the API base URL (defaults to ELIMU_API_BASE_URL from config).
    timeout : float, optional
        Per-request timeout in seconds.
    retries : int, optional
        Number of retry attempts on transient failures.
    backoff : float, optional
        Base backoff duration in seconds (exponential).
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = _DEFAULT_TIMEOUT,
        retries: int = _DEFAULT_RETRIES,
        backoff: float = _DEFAULT_BACKOFF,
    ) -> None:
        self._base_url = (base_url or ELIMU_API_BASE_URL).rstrip("/")
        self._timeout  = timeout
        self._retries  = retries
        self._backoff  = backoff
        self._session  = None  # lazily initialised

    # ── Session management ────────────────────────────────────────────────────

    def _get_session(self):
        """Lazily create and return a requests.Session with auth headers."""
        if self._session is not None:
            return self._session
        try:
            import requests
        except ImportError as exc:
            raise HTTPClientError(
                "requests is not installed. Run: pip install requests"
            ) from exc

        session = requests.Session()
        session.headers.update(
            {
                "Authorization": f"Bearer {AI_SHARED_SECRET}",
                "Content-Type":  "application/json",
                "Accept":        "application/json",
                "User-Agent":    "ElimuAI/2.1",
            }
        )
        self._session = session
        return session

    # ── Core request method ───────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Execute an HTTP request with retries and structured error handling.

        Returns the parsed JSON response body.
        Raises HTTPClientError subclasses on failure.
        """
        if not self._base_url:
            raise HTTPClientError(
                "ELIMU_API_BASE_URL is not configured. "
                "Set it in the environment before making API calls."
            )
        if not AI_SHARED_SECRET:
            raise AuthenticationError(
                "AI_SHARED_SECRET is not set. "
                "Every request requires a valid bearer token."
            )

        url = f"{self._base_url}{path}"
        session = self._get_session()
        last_exc: Exception | None = None

        for attempt in range(self._retries):
            try:
                logger.debug(
                    "http_client: %s %s (attempt %d/%d)",
                    method.upper(), url, attempt + 1, self._retries,
                )
                response = session.request(
                    method=method.upper(),
                    url=url,
                    json=payload,
                    params=params,
                    timeout=self._timeout,
                )

                if response.status_code == 401:
                    raise AuthenticationError(
                        f"API returned 401 Unauthorised for {url}. "
                        f"Check AI_SHARED_SECRET."
                    )
                if response.status_code == 403:
                    raise AuthenticationError(
                        f"API returned 403 Forbidden for {url}."
                    )
                if not response.ok:
                    raise HTTPResponseError(
                        f"API returned {response.status_code} for {url}: {response.text[:200]}",
                        status_code=response.status_code,
                    )

                logger.debug(
                    "http_client: %s %s → %d (%d bytes)",
                    method.upper(), url, response.status_code, len(response.content),
                )
                return response.json()

            except AuthenticationError:
                # Never retry auth errors
                raise
            except HTTPResponseError as exc:
                # Don't retry 4xx client errors
                if 400 <= exc.status_code < 500:
                    raise
                last_exc = exc
            except Exception as exc:
                import requests.exceptions as req_exc
                if isinstance(exc, req_exc.Timeout):
                    last_exc = HTTPTimeoutError(
                        f"Request to {url} timed out after {self._timeout}s."
                    )
                elif isinstance(exc, req_exc.ConnectionError):
                    last_exc = HTTPClientError(f"Connection failed: {url} — {exc}")
                else:
                    last_exc = exc

            wait = self._backoff ** attempt
            logger.warning(
                "http_client: attempt %d/%d failed for %s: %s — retrying in %.1fs",
                attempt + 1, self._retries, url, last_exc, wait,
            )
            time.sleep(wait)

        logger.error(
            "http_client: all %d attempts failed for %s %s",
            self._retries, method.upper(), url,
        )
        raise last_exc or HTTPClientError(f"Request failed: {method.upper()} {url}")

    # ── Convenience methods ───────────────────────────────────────────────────

    def get(
        self,
        path: str,
        params: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Perform an authenticated GET request."""
        return self._request("GET", path, params=params)

    def post(
        self,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Perform an authenticated POST request with a JSON payload."""
        return self._request("POST", path, payload=payload)

    # ── API-specific methods ──────────────────────────────────────────────────

    def chat(self, message: str, history: Optional[list] = None) -> Dict[str, Any]:
        """
        POST /api/ai/chat/
        Send a chat message to the Django AI endpoint.
        """
        return self.post("/api/ai/chat/", {
            "message": message,
            "history": history or [],
        })

    def submit_task(self, task_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        POST /api/ai/tasks/
        Submit a background task to the Django task queue.
        """
        return self.post("/api/ai/tasks/", {
            "task_type": task_type,
            "payload":   payload,
        })

    def get_task_result(self, task_id: str) -> Dict[str, Any]:
        """
        GET /api/ai/results/{task_id}/
        Poll for the result of a previously submitted task.
        """
        return self.get(f"/api/ai/results/{task_id}/")

    def api_health(self) -> Dict[str, Any]:
        """
        GET /api/ai/health/
        Check that the Django API is reachable and healthy.
        """
        return self.get("/api/ai/health/")

    def close(self) -> None:
        """Close the underlying requests session."""
        if self._session is not None:
            self._session.close()
            self._session = None
            logger.debug("http_client: session closed.")

    def __enter__(self) -> "ElimuAPIClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


# ── Module-level singleton (optional convenience) ─────────────────────────────

_default_client: Optional[ElimuAPIClient] = None


def get_client() -> ElimuAPIClient:
    """
    Return the shared ElimuAPIClient singleton.
    Creates it on first call.
    """
    global _default_client
    if _default_client is None:
        _default_client = ElimuAPIClient()
    return _default_client
