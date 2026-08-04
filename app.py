"""
app.py

ASGI entry point — the only file Uvicorn / Gunicorn should point at.

Exposes:
  application  — the FastAPI app from elimu_ai.service
  
Optionally starts the background scheduler on startup.

Run locally:
    uvicorn app:application --reload

Production:
    gunicorn app:application -k uvicorn.workers.UvicornWorker --workers 2
"""

import os

from elimu_ai.service import app as application  # noqa: F401 — re-exported for ASGI servers

# Start the background scheduler unless explicitly disabled
if os.getenv("DISABLE_SCHEDULER", "").lower() not in ("1", "true", "yes"):
    try:
        from elimu_ai.scheduler import start_scheduler
        start_scheduler(daemon=True)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Scheduler could not start: %s", exc)
