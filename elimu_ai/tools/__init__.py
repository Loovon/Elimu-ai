"""
elimu_ai/tools/__init__.py

Tool registry — exposes each tool function under a consistent name
so agent.py can import from a single namespace.
"""

from elimu_ai.tools.teacher import build_teacher_prompt
from elimu_ai.tools.quiz import build_quiz_prompt
from elimu_ai.tools.library import find_materials, build_librarian_prompt
from elimu_ai.tools.community import build_community_prompt
from elimu_ai.tools.forum import create_discussion
from elimu_ai.tools.moderation import moderate
from elimu_ai.tools.recommendations import recommend

__all__ = [
    "build_teacher_prompt",
    "build_quiz_prompt",
    "find_materials",
    "build_librarian_prompt",
    "build_community_prompt",
    "create_discussion",
    "moderate",
    "recommend",
]
