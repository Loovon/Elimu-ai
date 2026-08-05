"""
elimu_ai/db/connection.py

PostgreSQL connection management.

Uses a simple connection pool via psycopg2 (if available).
Falls back gracefully — all repositories degrade to no-ops when the
DB is unavailable or DATABASE_URL is not set.

Rules:
  - Never crash on DB unavailability.
  - All connections are returned to the pool via context managers.
  - Raw SQL is only executed here, never in repositories.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Any, Generator, Optional

from elimu_ai.config import DATABASE_URL

logger = logging.getLogger(__name__)

_pool = None
_pool_lock = threading.Lock()
_db_available: Optional[bool] = None   # cached availability check


def _get_pool():
    """Lazily create a connection pool. Returns None if DB unavailable."""
    global _pool, _db_available

    if _db_available is False:
        return None                # already known to be unavailable

    with _pool_lock:
        if _pool is not None:
            return _pool
        if not DATABASE_URL:
            logger.warning("db: DATABASE_URL not set — PostgreSQL disabled.")
            _db_available = False
            return None
        try:
            from psycopg2 import pool as pg_pool
            _pool = pg_pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=DATABASE_URL,
            )
            _db_available = True
            logger.info("db: PostgreSQL connection pool created.")
            return _pool
        except ImportError:
            logger.warning(
                "db: psycopg2 not installed — PostgreSQL disabled. "
                "Install with: pip install psycopg2-binary"
            )
            _db_available = False
            return None
        except Exception as exc:
            logger.warning("db: could not create connection pool: %s", exc)
            _db_available = False
            return None


@contextmanager
def get_connection() -> Generator[Any, None, None]:
    """
    Context manager that yields a psycopg2 connection from the pool.
    Automatically commits on success, rolls back on exception, returns to pool.

    Usage:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")

    Raises DBUnavailableError if the pool is not available.
    """
    from elimu_ai.exceptions import ElimuAIError

    pool = _get_pool()
    if pool is None:
        raise ElimuAIError("PostgreSQL is not available.")

    conn = None
    try:
        conn = pool.getconn()
        yield conn
        conn.commit()
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        if conn and pool:
            try:
                pool.putconn(conn)
            except Exception:
                pass


def db_available() -> bool:
    """Return True if a PostgreSQL connection can be established."""
    global _db_available
    if _db_available is not None:
        return _db_available
    return _get_pool() is not None
