"""
elimu_ai/logging_config.py

Centralised structured logging configuration.

Call configure_logging() once at application startup.
All other modules should use: logger = logging.getLogger(__name__)

Usage:
    from elimu_ai.logging_config import configure_logging
    configure_logging()
"""

from __future__ import annotations

import logging
import logging.config
import os


def configure_logging(level: str | None = None) -> None:
    """
    Apply the standard Elimu AI logging configuration.

    Parameters
    ----------
    level : str, optional
        Override the log level (e.g. "DEBUG", "WARNING").
        Defaults to the LOG_LEVEL environment variable, then "INFO".
    """
    effective_level = level or os.getenv("LOG_LEVEL", "INFO")

    config: dict = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "brief": {
                "format": "[%(levelname)s] %(name)s: %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "standard",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            # Silence noisy third-party loggers
            "httpx":              {"level": "WARNING", "propagate": True},
            "httpcore":           {"level": "WARNING", "propagate": True},
            "urllib3":            {"level": "WARNING", "propagate": True},
            "google":             {"level": "WARNING", "propagate": True},
            "qdrant_client":      {"level": "WARNING", "propagate": True},
            "apscheduler":        {"level": "INFO",    "propagate": True},
            "uvicorn.access":     {"level": "WARNING", "propagate": True},
        },
        "root": {
            "level": effective_level,
            "handlers": ["console"],
        },
    }

    logging.config.dictConfig(config)
    logging.getLogger(__name__).debug(
        "Logging configured at level=%s", effective_level
    )
