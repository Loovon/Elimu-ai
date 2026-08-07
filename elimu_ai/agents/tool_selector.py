"""
elimu_ai/agents/tool_selector.py

Tool Selector Agent — dynamically chooses the best tools for a plan step.
No hardcoded if/else chains. Uses the tool registry + resource availability.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class ToolSelectorAgent:
    """
    Selects and returns the callable tool for a given action name.
    Checks resource availability before selecting.
    Falls back to alternative tools when primary is unavailable.
    """

    # Maps action name → (primary_fn, fallback_fn)
    _FALLBACK_MAP: Dict[str, str] = {
        "qdrant_search":    "catalog_search",
        "catalog_search":   "qdrant_search",
        "teacher":          "catalog_search",
        "quiz":             "catalog_search",
        "recommendation":   "catalog_search",
        "librarian":        "catalog_search",
    }

    def select(self, action: str, params: Dict[str, Any]) -> Optional[Callable]:
        """
        Return the callable for the given action, or None if unavailable.
        Logs which tool was selected and why.
        """
        fn = self._get_tool(action)
        if fn:
            logger.debug("ToolSelector: selected %r", action)
            return fn

        # Try fallback
        fallback = self._FALLBACK_MAP.get(action)
        if fallback:
            fn = self._get_tool(fallback)
            if fn:
                logger.info(
                    "ToolSelector: %r unavailable, using fallback %r", action, fallback
                )
                return fn

        logger.warning("ToolSelector: no tool available for action %r", action)
        return None

    def available_actions(self) -> List[str]:
        """Return all action names that currently have a callable."""
        actions = []
        for name in self._ALL_TOOLS:
            if self._get_tool(name) is not None:
                actions.append(name)
        return actions

    _ALL_TOOLS = [
        "qdrant_search", "catalog_search", "forum_search",
        "teacher", "quiz", "librarian", "recommendation",
        "community", "moderation",
    ]

    def _get_tool(self, action: str) -> Optional[Callable]:
        """Return the callable for the action or None."""
        try:
            if action == "qdrant_search":
                from elimu_ai.qdrant_db import search
                from elimu_ai.config import QDRANT_URL
                if not QDRANT_URL:
                    return None
                return search

            elif action == "catalog_search":
                from elimu_ai.catalog_search import search_catalog, catalog_available
                if not catalog_available():
                    return None
                return search_catalog

            elif action == "forum_search":
                from elimu_ai.tools.forum import find_existing_threads
                return find_existing_threads

            elif action == "teacher":
                from elimu_ai.tool_registry import registry
                t = registry.get("teacher")
                return t.execute if t else None

            elif action == "quiz":
                from elimu_ai.tool_registry import registry
                t = registry.get("quiz")
                return t.execute if t else None

            elif action == "librarian":
                from elimu_ai.tool_registry import registry
                t = registry.get("librarian")
                return t.execute if t else None

            elif action == "recommendation":
                from elimu_ai.tool_registry import registry
                t = registry.get("recommendation")
                return t.execute if t else None

            elif action == "community":
                from elimu_ai.tool_registry import registry
                t = registry.get("community")
                return t.execute if t else None

            elif action == "moderation":
                from elimu_ai.tool_registry import registry
                t = registry.get("moderation")
                return t.execute if t else None

        except Exception as exc:
            logger.warning("ToolSelector: error loading %r: %s", action, exc)

        return None
