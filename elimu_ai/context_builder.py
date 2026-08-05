"""
elimu_ai/context_builder.py

AI Context Builder — assembles the full Gemini prompt context before every call.

Responsibilities:
  - Merge conversation history
  - Include Qdrant semantic search results
  - Include catalog search results
  - Include user persona + curriculum context
  - Include current scheduler / system state if relevant

Rules:
  - Never calls Gemini directly (no generation).
  - Never modifies state.
  - Pure assembly function: inputs → PromptContext dataclass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PromptContext:
    """
    Assembled context passed to Gemini generation calls.

    Attributes
    ----------
    question : str
        The user's current message.
    persona : str
        Which AI persona is responding.
    intents : list[str]
        Detected intent names in confidence order.
    qdrant_context : str
        Formatted Qdrant semantic search results.
    catalog_context : str
        Formatted catalog search results.
    conversation_history : list[dict]
        Recent {role, content} conversation turns.
    curriculum_hints : dict
        Extracted grade, subject, term, year, audience.
    system_note : str
        Optional system-level context (e.g. current term, scheduler status).
    raw_hits : list
        Raw Qdrant ScoredPoint objects (for source URL extraction).
    """
    question: str
    persona: str
    intents: List[str] = field(default_factory=list)
    qdrant_context: str = ""
    catalog_context: str = ""
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    curriculum_hints: Dict[str, Optional[str]] = field(default_factory=dict)
    system_note: str = ""
    raw_hits: List[Any] = field(default_factory=list)

    def to_context_string(self) -> str:
        """
        Render all context sources into a single plain-text block
        for injection into Gemini prompts.
        """
        parts: List[str] = []

        if self.curriculum_hints:
            hints = {k: v for k, v in self.curriculum_hints.items() if v}
            if hints:
                parts.append("Curriculum context: " + ", ".join(
                    f"{k}={v}" for k, v in hints.items()
                ))

        if self.qdrant_context:
            parts.append("Relevant documents from Elimu Library:\n" + self.qdrant_context)

        if self.catalog_context:
            parts.append("Catalog results:\n" + self.catalog_context)

        if self.system_note:
            parts.append("System note: " + self.system_note)

        if not parts:
            return "No additional context available."

        return "\n\n".join(parts)


def build_context(
    question: str,
    persona: str,
    intents: Optional[List[str]] = None,
    history: Optional[List[Dict[str, str]]] = None,
    curriculum_hints: Optional[Dict[str, Optional[str]]] = None,
    qdrant_hits: Optional[List[Any]] = None,
    catalog_results: Optional[str] = None,
    include_system_note: bool = True,
) -> PromptContext:
    """
    Assemble a PromptContext from all available inputs.

    Parameters
    ----------
    question : str
        The user's current message.
    persona : str
        The selected persona name.
    intents : list[str], optional
        Detected intent names.
    history : list[dict], optional
        Prior conversation turns [{role, content}].
    curriculum_hints : dict, optional
        Extracted grade, subject, term, year, audience.
    qdrant_hits : list, optional
        Raw ScoredPoint objects from Qdrant search.
    catalog_results : str, optional
        Pre-formatted catalog search results string.
    include_system_note : bool
        Whether to append current term/year information.

    Returns
    -------
    PromptContext
    """
    # Build Qdrant context string
    qdrant_ctx = _format_qdrant_hits(qdrant_hits or [])

    # System note
    system_note = ""
    if include_system_note:
        system_note = _build_system_note()

    return PromptContext(
        question=question,
        persona=persona,
        intents=intents or [],
        qdrant_context=qdrant_ctx,
        catalog_context=catalog_results or "",
        conversation_history=_trim_history(history or []),
        curriculum_hints=curriculum_hints or {},
        system_note=system_note,
        raw_hits=qdrant_hits or [],
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _format_qdrant_hits(hits: List[Any]) -> str:
    """Convert Qdrant ScoredPoint objects to a plain-text block."""
    if not hits:
        return ""
    parts = []
    for hit in hits:
        p = hit.payload or {}
        title = p.get("title", "")
        desc  = p.get("description", "")
        url   = p.get("url", "")
        chunk = p.get("text", "")[:300] if p.get("text") else ""
        entry = f"Title: {title}"
        if desc:
            entry += f"\nDescription: {desc}"
        if url:
            entry += f"\nURL: {url}"
        if chunk:
            entry += f"\nExcerpt: {chunk}"
        parts.append(entry)
    return "\n\n".join(parts)


def _trim_history(
    history: List[Dict[str, str]],
    max_turns: int = 6,
    max_chars: int = 2000,
) -> List[Dict[str, str]]:
    """
    Keep the last max_turns messages without exceeding max_chars total.
    Always preserve the most recent turns.
    """
    trimmed = history[-max_turns:]
    total = sum(len(m.get("content", "")) for m in trimmed)
    while trimmed and total > max_chars:
        removed = trimmed.pop(0)
        total -= len(removed.get("content", ""))
    return trimmed


def _build_system_note() -> str:
    """Return a brief system context note (current Kenya term/year)."""
    try:
        from elimu_ai.catalog_search import current_term, current_year
        return f"Current Kenya school term: Term {current_term()}, {current_year()}."
    except Exception:
        return ""
