"""
elimu_ai/tools/community.py

Community tool — builds prompts for discussion, forum, and community content.
Responsibilities:
  - build_community_prompt(question, context) → str

Rules:
  - NEVER calls generate() directly.
  - NEVER imports service.py.
  - NEVER makes HTTP requests inside prompt builders.
  - Django / forum integration is isolated in forum.py.
"""

from __future__ import annotations

from elimu_ai.prompts import COMMUNITY_PROMPT


def build_community_prompt(question: str, context: str = "") -> str:
    """
    Build and return a community discussion prompt string.
    Does NOT call Gemini.
    """
    return COMMUNITY_PROMPT.format(
        question=question,
        context=context or "General ElimuTalks community discussion.",
    )
