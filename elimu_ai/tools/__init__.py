"""
elimu_ai/tools/__init__.py

Tool registry.

Imports are lazy (inside functions) for tools that require optional runtime
dependencies (Django, etc.) so the package always imports cleanly regardless
of the deployment environment.

For direct use, import from the individual module:
    from elimu_ai.tools.teacher import build_teacher_prompt
    from elimu_ai.tools.library import find_materials
"""

# Re-export the safe, always-available tools at module level
from elimu_ai.tools.teacher import (
    build_teacher_prompt,
    extract_context_hints,
    extract_context_from_history,
)
from elimu_ai.tools.quiz import build_quiz_prompt, quiz_fallback
from elimu_ai.tools.library import find_materials, build_librarian_prompt
from elimu_ai.tools.community import build_community_prompt
from elimu_ai.tools.moderation import moderate
from elimu_ai.tools.recommendations import recommend

# Tools with optional runtime dependencies are imported on demand.
# Use:  from elimu_ai.tools.forum import create_discussion
# Use:  from elimu_ai.tools.answer import answer_unanswered_threads

__all__ = [
    # Teacher
    "build_teacher_prompt",
    "extract_context_hints",
    "extract_context_from_history",
    # Quiz
    "build_quiz_prompt",
    "quiz_fallback",
    # Library
    "find_materials",
    "build_librarian_prompt",
    # Community
    "build_community_prompt",
    # Moderation
    "moderate",
    # Recommendations
    "recommend",
]
