"""
elimu_ai/http_client.py

The SINGLE communication boundary between the AI worker and the Django application.

Rules:
  - All Django operations go through this client via HTTP.
  - No Django ORM imports anywhere in the AI worker.
  - Bearer token is never logged.
  - Retry logic: exponential backoff + jitter on transient errors only.
  - Non-idempotent POSTs (create discussion, post answer) carry Idempotency-Key.
  - 4xx errors are never retried (except 408, 425, 429).

API contracts (Django must implement these endpoints):
  GET  /api/ai/health/
  GET  /api/ai/forum/unanswered/
  GET  /api/ai/forum/search/?q=<topic>
  POST /api/ai/forum/discussions/        body: {title, body, category}
  POST /api/ai/forum/posts/              body: {thread_id, content, ai_generated}
  POST /api/ai/forum/answers/            body: {thread_id, content, idempotency_key}
  GET  /api/ai/catalog/status/
  POST /api/ai/moderation/check/         body: {content}
  GET  /api/ai/tasks/{task_id}/
  POST /api/ai/tasks/                    body: {task_type, payload}
"""

from __future__ import annotations

import logging
import random
import time
import uuid
from typing import Any, Dict, List, Optional

from elimu_ai.config import AI_SHARED_SECRET, ELIMU_API_BASE_URL
from elimu_ai.exceptions import (
    AuthenticationError,
    HTTPClientError,
    HTTPResponseError,
    HTTPTimeoutError,
)

logger = logging.getLogger(__name__)

# ── Retry configuration ───────────────────────────────────────────────────────
_DEFAULT_TIMEOUT   = 15.0
_DEFAULT_RETRIES   = 3
_DEFAULT_BACKOFF   = 1.5
_JITTER_MAX        = 0.5
_RETRYABLE_STATUSES = {408, 425, 429, 500, 502, 503, 504}
_NO_RETRY_STATUSES  = {400, 401, 403, 404, 405, 409, 410, 422}


def _backoff_with_jitter(attempt: int, base: float) -> float:
    """Exponential backoff with uniform jitter."""
    return (base ** attempt) + random.uniform(0, _JITTER_MAX)


class ElimuAPIClient:
    """
    Authenticated HTTP client for the ElimuTalks Django REST API.
    This is the ONLY way the AI worker communicates with Django.
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
        self._session  = None

    def _get_session(self):
        if self._session is not None:
            return self._session
        try:
            import requests
        except ImportError as exc:
            raise HTTPClientError("requests not installed") from exc
        s = requests.Session()
        # Authorization header is set here — never logged
        s.headers.update({
            "Authorization": f"Bearer {AI_SHARED_SECRET}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
            "User-Agent":    "ElimuAI-Worker/2.2",
        })
        self._session = s
        return s

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self._base_url:
            raise HTTPClientError("ELIMU_API_BASE_URL is not configured.")
        if not AI_SHARED_SECRET:
            raise AuthenticationError("AI_SHARED_SECRET is not set.")

        url     = f"{self._base_url}{path}"
        session = self._get_session()
        last_exc: Exception | None = None

        extra_headers: Dict[str, str] = {}
        if idempotency_key:
            extra_headers["Idempotency-Key"] = idempotency_key

        for attempt in range(self._retries):
            try:
                logger.debug("http: %s %s (attempt %d)", method.upper(), path, attempt + 1)
                resp = session.request(
                    method=method.upper(),
                    url=url,
                    json=payload,
                    params=params,
                    timeout=self._timeout,
                    headers=extra_headers,
                )

                if resp.status_code == 401:
                    raise AuthenticationError("API returned 401 — check AI_SHARED_SECRET.")
                if resp.status_code == 403:
                    raise AuthenticationError("API returned 403 Forbidden.")

                if not resp.ok:
                    exc = HTTPResponseError(
                        f"API {method.upper()} {path} → {resp.status_code}",
                        status_code=resp.status_code,
                    )
                    if resp.status_code in _NO_RETRY_STATUSES:
                        raise exc
                    # Check for Retry-After header
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after and attempt < self._retries - 1:
                        try:
                            time.sleep(float(retry_after))
                        except ValueError:
                            pass
                    last_exc = exc
                    if resp.status_code not in _RETRYABLE_STATUSES:
                        raise exc
                else:
                    logger.debug("http: %s %s → %d", method.upper(), path, resp.status_code)
                    try:
                        return resp.json()
                    except Exception:
                        return {"status": "ok", "raw": resp.text[:500]}

            except AuthenticationError:
                raise
            except HTTPResponseError as exc:
                if exc.status_code not in _RETRYABLE_STATUSES:
                    raise
                last_exc = exc
            except Exception as exc:
                try:
                    import requests.exceptions as rex
                    if isinstance(exc, rex.Timeout):
                        last_exc = HTTPTimeoutError(f"Timeout on {url}")
                    elif isinstance(exc, rex.ConnectionError):
                        last_exc = HTTPClientError(f"Connection failed: {url}")
                    else:
                        last_exc = exc
                except ImportError:
                    last_exc = exc

            # Don't sleep after last attempt
            if attempt < self._retries - 1:
                wait = _backoff_with_jitter(attempt, self._backoff)
                logger.warning("http: attempt %d failed for %s %s — retry in %.1fs: %s",
                               attempt + 1, method.upper(), path, wait, last_exc)
                time.sleep(wait)

        logger.error("http: all %d attempts failed for %s %s", self._retries, method.upper(), path)
        raise last_exc or HTTPClientError(f"Request failed: {method.upper()} {path}")

    # ── Low-level methods ─────────────────────────────────────────────────────

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._request("GET", path, params=params)

    def post(self, path: str, payload: Optional[Dict[str, Any]] = None,
             idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        return self._request("POST", path, payload=payload, idempotency_key=idempotency_key)

    # ── Forum API ─────────────────────────────────────────────────────────────

    def get_unanswered_threads(
        self,
        cutoff_hours: int = 3,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """GET /api/ai/forum/unanswered/"""
        return self.get("/api/ai/forum/unanswered/", {
            "cutoff_hours": str(cutoff_hours),
            "page":      str(page),
            "page_size": str(page_size),
        })

    def search_threads(self, query: str, limit: int = 5) -> Dict[str, Any]:
        """GET /api/ai/forum/search/?q=<query>"""
        return self.get("/api/ai/forum/search/", {"q": query, "limit": str(limit)})

    def get_thread_detail(self, thread_id: int) -> Dict[str, Any]:
        """GET /api/ai/forum/threads/{id}/ — returns thread metadata + posts."""
        return self.get(f"/api/ai/forum/threads/{thread_id}/")

    def get_active_threads(
        self,
        min_posts: int = 2,
        max_posts: int = 29,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """
        GET /api/ai/forum/active/ — threads with activity below the growth target.
        Returns threads that need continuation (min_posts < post_count < max_posts).
        """
        return self.get("/api/ai/forum/active/", {
            "min_posts": str(min_posts),
            "max_posts": str(max_posts),
            "limit":     str(limit),
        })

    def create_discussion(
        self,
        title: str,
        body: str,
        category: str,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """POST /api/ai/forum/discussions/"""
        key = idempotency_key or f"ai-discussion-{uuid.uuid5(uuid.NAMESPACE_URL, title).hex}"
        return self.post("/api/ai/forum/discussions/", {
            "title": title,
            "body":  body,
            "category": category,
            "ai_generated": True,
        }, idempotency_key=key)

    def post_answer(
        self,
        thread_id: int,
        content: str,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        POST /api/ai/forum/answers/
        Idempotency-Key prevents duplicate answers on network retries.
        """
        key = idempotency_key or f"ai-forum-answer-{thread_id}"
        return self.post("/api/ai/forum/answers/", {
            "thread_id":    thread_id,
            "content":      content,
            "ai_generated": True,
        }, idempotency_key=key)

    def check_moderation(self, content: str) -> Dict[str, Any]:
        """POST /api/ai/moderation/check/"""
        return self.post("/api/ai/moderation/check/", {"content": content})

    # ── Catalog API ───────────────────────────────────────────────────────────

    def get_catalog_status(self) -> Dict[str, Any]:
        """GET /api/ai/catalog/status/"""
        return self.get("/api/ai/catalog/status/")

    # ── Health / Tasks ────────────────────────────────────────────────────────

    def api_health(self) -> Dict[str, Any]:
        """GET /api/ai/health/"""
        return self.get("/api/ai/health/")

    def submit_task(self, task_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.post("/api/ai/tasks/", {"task_type": task_type, "payload": payload})

    def get_task_result(self, task_id: str) -> Dict[str, Any]:
        return self.get(f"/api/ai/tasks/{task_id}/")

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None
            logger.debug("http_client: session closed.")

    def __enter__(self) -> "ElimuAPIClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


# ── Module-level singleton ────────────────────────────────────────────────────

_default_client: Optional[ElimuAPIClient] = None


def get_client() -> ElimuAPIClient:
    global _default_client
    if _default_client is None:
        _default_client = ElimuAPIClient()
    return _default_client
