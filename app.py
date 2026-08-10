"""
app.py — FastAPI ASGI entry point for the API service only.

IMPORTANT: Background workers (scheduler / agent_manager) must run in the
dedicated worker process (elimu_ai/worker.py), NOT in this web process.

Set DISABLE_SCHEDULER=1 and DISABLE_AGENT_MANAGER=1 in production
when running alongside the worker process to avoid duplicate schedulers.

Local development (single process):
    uvicorn app:application --reload
    # Scheduler and agent_manager start via env defaults below.

Production (separate worker):
    # Web:    gunicorn app:application -k uvicorn.workers.UvicornWorker
    # Worker: python -m elimu_ai.worker
"""

import logging
import os

from elimu_ai.service import app as application  # noqa: F401

_log = logging.getLogger(__name__)

# ── Only start background workers if explicitly enabled ───────────────────────
# In production, set DISABLE_SCHEDULER=1 and DISABLE_AGENT_MANAGER=1
# so that background work runs only in the dedicated worker process.

_DISABLE_SCHEDULER     = os.getenv("DISABLE_SCHEDULER", "").lower() in ("1", "true", "yes")
_DISABLE_AGENT_MANAGER = os.getenv("DISABLE_AGENT_MANAGER", "").lower() in ("1", "true", "yes")
_DISABLE_DB_MIGRATIONS = os.getenv("DISABLE_DB_MIGRATIONS", "").lower() in ("1", "true", "yes")

if not _DISABLE_SCHEDULER:
    try:
        from elimu_ai.scheduler import start_scheduler
        start_scheduler(daemon=True)
        _log.info("app: scheduler started (set DISABLE_SCHEDULER=1 in production worker mode)")
    except Exception as exc:
        _log.warning("app: scheduler failed to start: %s", exc)

if not _DISABLE_AGENT_MANAGER:
    try:
        from elimu_ai.agent_manager import start_agent_manager
        start_agent_manager(daemon=True)
        _log.info("app: agent_manager started (set DISABLE_AGENT_MANAGER=1 in production worker mode)")
    except Exception as exc:
        _log.warning("app: agent_manager failed to start: %s", exc)

if not _DISABLE_DB_MIGRATIONS:
    try:
        from elimu_ai.db.migrations import run_migrations
        run_migrations()
    except Exception as exc:
        _log.warning("app: DB migrations failed (non-fatal): %s", exc)
