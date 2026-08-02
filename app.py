"""
app.py

ASGI application entry point for production deployment.
Exposes the FastAPI app from elimu_ai.service as `application`
for use with Gunicorn + Uvicorn workers.

Run locally:
    uvicorn app:application --reload

Production:
    gunicorn app:application -k uvicorn.workers.UvicornWorker
"""

from elimu_ai.service import app as application  # noqa: F401  (re-exported for ASGI servers)
