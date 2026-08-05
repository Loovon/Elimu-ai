"""
elimu_ai/tool_registry.py

Declarative Tool Registry.

Every tool is registered with:
  - name            : unique identifier
  - description     : what the tool does
  - supported_intents: which intents trigger this tool
  - priority        : higher = preferred when multiple tools match
  - required_resources: what the tool needs (gemini, qdrant, catalog, django)
  - dependencies    : other tool names that must run first (for chaining)

Usage:
    from elimu_ai.tool_registry import registry

    # Get tools for detected intents
    tools = registry.tools_for_intents(["quiz", "recommendation"])

    # Execute a tool by name
    result = registry.execute("quiz", context=ctx, question=q)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """Metadata and execution function for a single tool."""
    name: str
    description: str
    supported_intents: Set[str]
    priority: int                       # higher = preferred
    required_resources: Set[str]        # "gemini", "qdrant", "catalog", "django"
    dependencies: List[str]             # tool names that must run first
    execute: Callable[..., str]         # callable(context, **kwargs) → str
    enabled: bool = True


class ToolRegistry:
    """
    Central registry of all AI tools.
    Supports intent-based lookup and sequential execution planning.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool definition."""
        self._tools[tool.name] = tool
        logger.debug("ToolRegistry: registered %r (intents=%s)", tool.name, tool.supported_intents)

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Return a tool by name, or None."""
        return self._tools.get(name)

    def tools_for_intents(
        self,
        intents: List[str],
        exclude_resources: Optional[Set[str]] = None,
    ) -> List[ToolDefinition]:
        """
        Return tools that support any of the given intents,
        sorted by priority descending.

        Parameters
        ----------
        intents : list[str]
            Detected intent names.
        exclude_resources : set[str], optional
            Skip tools that require unavailable resources.
        """
        matches: List[ToolDefinition] = []
        seen: Set[str] = set()

        for intent in intents:
            for tool in self._tools.values():
                if not tool.enabled:
                    continue
                if tool.name in seen:
                    continue
                if intent in tool.supported_intents:
                    if exclude_resources and tool.required_resources & exclude_resources:
                        continue
                    matches.append(tool)
                    seen.add(tool.name)

        matches.sort(key=lambda t: t.priority, reverse=True)
        return matches

    def execution_plan(
        self,
        intents: List[str],
        exclude_resources: Optional[Set[str]] = None,
    ) -> List[ToolDefinition]:
        """
        Build an ordered execution plan for the given intents,
        respecting tool dependencies.
        """
        candidates = self.tools_for_intents(intents, exclude_resources)
        planned: List[ToolDefinition] = []
        planned_names: Set[str] = set()

        def _add(tool: ToolDefinition) -> None:
            # Resolve dependencies first
            for dep_name in tool.dependencies:
                dep = self._tools.get(dep_name)
                if dep and dep.name not in planned_names:
                    _add(dep)
            if tool.name not in planned_names:
                planned.append(tool)
                planned_names.add(tool.name)

        for tool in candidates:
            _add(tool)

        return planned

    def all_names(self) -> List[str]:
        return list(self._tools.keys())


# ── Tool execution wrappers ───────────────────────────────────────────────────

def _execute_teacher(context: Any, question: str, **_) -> str:
    from elimu_ai.gemini import generate
    from elimu_ai.tools.teacher import build_teacher_prompt
    prompt = build_teacher_prompt(question, context.to_context_string())
    return generate(prompt)


def _execute_quiz(context: Any, question: str, **_) -> str:
    from elimu_ai.gemini import generate
    from elimu_ai.tools.quiz import build_quiz_prompt, quiz_fallback
    prompt = build_quiz_prompt(question, context.qdrant_context)
    result = generate(prompt)
    if result.startswith("Elimu AI") or result.startswith("Gemini error"):
        return quiz_fallback(question)
    return result


def _execute_librarian(context: Any, question: str, **_) -> str:
    from elimu_ai.tools.library import find_materials
    return find_materials(
        question=question,
        grade=context.curriculum_hints.get("grade"),
        subject=context.curriculum_hints.get("subject"),
        term=context.curriculum_hints.get("term"),
        year=context.curriculum_hints.get("year"),
        audience=context.curriculum_hints.get("audience"),
    )


def _execute_recommendation(context: Any, question: str, **_) -> str:
    from elimu_ai.tools.recommendations import recommend
    return recommend(
        question=question,
        grade=context.curriculum_hints.get("grade"),
        subject=context.curriculum_hints.get("subject"),
        term=context.curriculum_hints.get("term"),
        year=context.curriculum_hints.get("year"),
        audience=context.curriculum_hints.get("audience"),
    )


def _execute_community(context: Any, question: str, **_) -> str:
    from elimu_ai.tools.forum import create_discussion
    return create_discussion(question)


def _execute_catalog(context: Any, question: str, **_) -> str:
    from elimu_ai.catalog_search import search_catalog, format_recommendations
    results = search_catalog(keyword=question, max_results=5)
    return format_recommendations(results, question)


def _execute_moderation(context: Any, question: str, **_) -> str:
    from elimu_ai.tools.moderation import moderate
    return moderate(question)


# ── Build the global registry ─────────────────────────────────────────────────

def _build_registry() -> ToolRegistry:
    reg = ToolRegistry()

    reg.register(ToolDefinition(
        name="teacher",
        description="Explain educational concepts using Kenyan CBC/8-4-4 curriculum context",
        supported_intents={"teacher", "general_chat", "search"},
        priority=70,
        required_resources={"gemini"},
        dependencies=[],
        execute=_execute_teacher,
    ))

    reg.register(ToolDefinition(
        name="quiz",
        description="Generate practice questions, MCQs, and structured exam questions",
        supported_intents={"quiz"},
        priority=90,
        required_resources={"gemini"},
        dependencies=[],
        execute=_execute_quiz,
    ))

    reg.register(ToolDefinition(
        name="librarian",
        description="Find and recommend specific documents from the Elimu Library catalog",
        supported_intents={"librarian", "search"},
        priority=85,
        required_resources={"catalog"},
        dependencies=[],
        execute=_execute_librarian,
    ))

    reg.register(ToolDefinition(
        name="recommendation",
        description="Recommend relevant learning materials based on subject and grade",
        supported_intents={"recommendation", "librarian"},
        priority=80,
        required_resources={"catalog"},
        dependencies=[],
        execute=_execute_recommendation,
    ))

    reg.register(ToolDefinition(
        name="community",
        description="Create or find forum discussions on ElimuTalks",
        supported_intents={"community", "discussion"},
        priority=75,
        required_resources={"gemini"},
        dependencies=[],
        execute=_execute_community,
    ))

    reg.register(ToolDefinition(
        name="catalog",
        description="Browse and search the Elimu Library catalog",
        supported_intents={"catalog", "search"},
        priority=65,
        required_resources={"catalog"},
        dependencies=[],
        execute=_execute_catalog,
    ))

    reg.register(ToolDefinition(
        name="moderation",
        description="Check content for spam and policy violations",
        supported_intents={"moderation"},
        priority=95,
        required_resources=set(),
        dependencies=[],
        execute=_execute_moderation,
    ))

    return reg


# Global singleton registry
registry: ToolRegistry = _build_registry()
