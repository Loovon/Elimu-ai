"""
elimu_ai/memory.py

Conversation and long-term memory.

Layers:
  1. In-process short-term memory (dict keyed by session_id)
     — Fast, no DB required
  2. PostgreSQL-backed long-term memory via MemoryRepository
     — Summaries stored periodically, not raw conversations
     — Falls back gracefully when DB is unavailable

Rules:
  - Never store raw conversations permanently.
  - Summarise after SUMMARY_AFTER_TURNS turns.
  - Never crash if PostgreSQL is unavailable.
  - Session IDs are caller-managed strings.

Usage:
    from elimu_ai.memory import memory_store

    # Add a turn
    memory_store.add_turn("session-123", "user", "What is osmosis?")
    memory_store.add_turn("session-123", "assistant", "Osmosis is...")

    # Get recent history
    history = memory_store.get_history("session-123", max_turns=6)

    # Save summary to DB
    memory_store.save_summary("session-123", user_id=42)
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
SUMMARY_AFTER_TURNS = 12   # summarise after this many turns
MAX_IN_MEMORY_TURNS = 50   # maximum turns held in RAM per session


class MemoryStore:
    """
    Thread-safe in-process conversation store with optional PostgreSQL persistence.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # session_id → list of {role, content, timestamp}
        self._sessions: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        # session_id → turn count since last summary
        self._turns_since_summary: Dict[str, int] = defaultdict(int)

    # ── Core operations ───────────────────────────────────────────────────────

    def add_turn(
        self,
        session_id: str,
        role: str,
        content: str,
    ) -> None:
        """Append one conversation turn to the in-memory store."""
        with self._lock:
            turns = self._sessions[session_id]
            turns.append({
                "role":      role,
                "content":   content,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            })
            # Evict oldest if over limit
            if len(turns) > MAX_IN_MEMORY_TURNS:
                evicted = turns[:len(turns) - MAX_IN_MEMORY_TURNS]
                self._sessions[session_id] = turns[len(turns) - MAX_IN_MEMORY_TURNS:]
                logger.debug(
                    "memory: evicted %d old turns for session %r",
                    len(evicted), session_id[:16],
                )
            self._turns_since_summary[session_id] += 1

    def get_history(
        self,
        session_id: str,
        max_turns: int = 6,
    ) -> List[Dict[str, str]]:
        """
        Return the last max_turns conversation turns as {role, content} dicts.
        Trims timestamp field — returns only what Gemini expects.
        """
        with self._lock:
            turns = self._sessions.get(session_id, [])
            recent = turns[-max_turns:]
        return [{"role": t["role"], "content": t["content"]} for t in recent]

    def clear_session(self, session_id: str) -> None:
        """Remove all in-memory turns for a session."""
        with self._lock:
            self._sessions.pop(session_id, None)
            self._turns_since_summary.pop(session_id, None)

    def should_summarise(self, session_id: str) -> bool:
        """Return True if this session has accumulated enough turns to summarise."""
        with self._lock:
            return self._turns_since_summary.get(session_id, 0) >= SUMMARY_AFTER_TURNS

    def session_ids(self) -> List[str]:
        """Return all active session IDs."""
        with self._lock:
            return list(self._sessions.keys())

    # ── Summary generation + DB persistence ──────────────────────────────────

    def save_summary(
        self,
        session_id: str,
        user_id: Optional[int] = None,
        force: bool = False,
    ) -> Optional[str]:
        """
        Summarise the session conversation using Gemini and store in PostgreSQL.

        Parameters
        ----------
        session_id : str
            The session to summarise.
        user_id : int, optional
            The user ID to associate the summary with.
        force : bool
            If True, summarise even if SUMMARY_AFTER_TURNS has not been reached.

        Returns
        -------
        str | None
            The generated summary text, or None if skipped / failed.
        """
        if not force and not self.should_summarise(session_id):
            return None

        history = self.get_history(session_id, max_turns=SUMMARY_AFTER_TURNS)
        if not history:
            return None

        summary = self._generate_summary(history)
        if not summary:
            return None

        # Persist to DB (graceful failure)
        self._store_summary(session_id, user_id, summary)

        # Reset the counter
        with self._lock:
            self._turns_since_summary[session_id] = 0

        logger.info(
            "memory: saved summary for session %r (user_id=%s, chars=%d)",
            session_id[:16], user_id, len(summary),
        )
        return summary

    def _generate_summary(self, history: List[Dict[str, str]]) -> Optional[str]:
        """Use Gemini to summarise the conversation history."""
        try:
            from elimu_ai.gemini import generate
            turns_text = "\n".join(
                f"{t['role'].capitalize()}: {t['content'][:200]}"
                for t in history
            )
            prompt = (
                "Summarise this student–AI conversation in 2–3 plain-text sentences. "
                "Focus on the educational topics covered and what was learned.\n\n"
                + turns_text
            )
            result = generate(prompt)
            if result.startswith("Elimu AI") or result.startswith("Gemini error"):
                return None
            return result.strip()
        except Exception as exc:
            logger.warning("memory: summary generation failed: %s", exc)
            return None

    def _store_summary(
        self,
        session_id: str,
        user_id: Optional[int],
        summary: str,
    ) -> None:
        """Persist the summary to the MemoryRepository (DB)."""
        try:
            from elimu_ai.db.repositories import MemoryRepository
            repo = MemoryRepository()
            repo.save_summary(
                session_id=session_id,
                user_id=user_id,
                summary=summary,
            )
        except Exception as exc:
            logger.warning("memory: DB persist failed (non-fatal): %s", exc)

    def load_user_summaries(
        self,
        user_id: int,
        max_summaries: int = 3,
    ) -> List[str]:
        """
        Load recent conversation summaries for a user from the DB.
        Returns [] if DB is unavailable.
        """
        try:
            from elimu_ai.db.repositories import MemoryRepository
            repo = MemoryRepository()
            return repo.get_summaries(user_id=user_id, limit=max_summaries)
        except Exception as exc:
            logger.warning("memory: load_user_summaries failed: %s", exc)
            return []


# ── Global singleton ──────────────────────────────────────────────────────────

memory_store: MemoryStore = MemoryStore()
