"""
elimu_ai/worker.py — Dedicated long-running background worker process.

Run as a SEPARATE process from the FastAPI web workers:
    python -m elimu_ai.worker

This process owns:
  - APScheduler (all background tasks)
  - AgentManager (continuous observer)
  - DB migrations (idempotent)

The FastAPI web process (app.py / uvicorn) should set:
    DISABLE_SCHEDULER=1
    DISABLE_AGENT_MANAGER=1

so that background work runs in exactly ONE place — this worker.

Lifecycle:
  START → load config → validate → init clients → migrations
        → start scheduler → start agent_manager
        → loop (SIGTERM/SIGINT) → graceful shutdown → EXIT
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

# ── Bootstrap ─────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env.local", override=True)
    load_dotenv(Path(__file__).parent.parent / ".env",       override=False)
except ImportError:
    pass

from elimu_ai.logging_config import configure_logging
configure_logging()
logger = logging.getLogger("elimu_worker")


def validate_config() -> None:
    """Fail fast if critical worker configuration is missing."""
    from elimu_ai.config import GEMINI_API_KEY, QDRANT_URL, ELIMU_API_BASE_URL
    warnings = []
    if not GEMINI_API_KEY:
        warnings.append("GEMINI_API_KEY not set — Gemini calls will fail")
    if not QDRANT_URL:
        warnings.append("QDRANT_URL not set — vector search disabled")
    if not ELIMU_API_BASE_URL:
        warnings.append("ELIMU_API_BASE_URL not set — Django API calls will fail")
    for w in warnings:
        logger.warning("worker config: %s", w)


def run_migrations() -> None:
    try:
        from elimu_ai.db.migrations import run_migrations as _migrate
        _migrate()
    except Exception as exc:
        logger.warning("worker: DB migrations failed (non-fatal): %s", exc)


def main() -> None:
    logger.info("=" * 60)
    logger.info("Elimu AI Worker starting")
    logger.info("  PID: %d", os.getpid())
    logger.info("=" * 60)

    validate_config()
    run_migrations()

    from elimu_ai.scheduler    import start_scheduler,     shutdown_scheduler
    from elimu_ai.agent_manager import start_agent_manager, stop_agent_manager

    stop_event = threading.Event()

    def _handle_signal(signum, frame):
        logger.info("Worker: received signal %d — initiating graceful shutdown.", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    # ── Start background services ────────────────────────────────────────────
    logger.info("Worker: starting APScheduler…")
    start_scheduler(daemon=False)   # non-daemon so process stays alive

    logger.info("Worker: starting AgentManager…")
    start_agent_manager(daemon=True)

    logger.info("Worker: running. Send SIGTERM or SIGINT to stop.")

    # ── Keep alive ────────────────────────────────────────────────────────────
    while not stop_event.is_set():
        time.sleep(1)

    # ── Graceful shutdown ─────────────────────────────────────────────────────
    logger.info("Worker: shutting down AgentManager…")
    stop_agent_manager()

    logger.info("Worker: shutting down scheduler…")
    shutdown_scheduler(wait=True)

    # Close shared HTTP client session
    try:
        from elimu_ai.http_client import get_client
        get_client().close()
    except Exception:
        pass

    logger.info("Worker: exited cleanly.")
    sys.exit(0)


if __name__ == "__main__":
    main()
