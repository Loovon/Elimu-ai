"""
elimu_ai/tools/community.py

Community tool — prompt builder for the community persona.
Responsibilities:
  - build_community_prompt(question, context) → str

Rules:
  - Never calls generate().
  - Never imports service.py.
  - No network requests.
  - Django / forum orchestration lives in forum.py.
"""

from __future__ import annotations

from elimu_ai.prompts import COMMUNITY_PROMPT


def build_community_prompt(question: str, context: str = "") -> str:
    """
    Render and return the community persona prompt string.
    Does NOT call Gemini.
    """
    return COMMUNITY_PROMPT.format(
        question=question,
        context=context or "General ElimuTalks community discussion.",
    )
