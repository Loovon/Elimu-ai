"""
elimu_ai/tools/quiz.py

Quiz tool — builds the prompt for the quiz persona.
Responsibilities:
  - build_quiz_prompt(question, context) → str

Rules:
  - NEVER calls generate() directly.
  - NEVER imports service.py.
  - NEVER imports chromadb, ollama, or any removed dependency.
  - NEVER makes HTTP requests.
  - Only builds and returns prompt strings.
"""

from __future__ import annotations

from elimu_ai.prompts import QUIZ_PROMPT


def build_quiz_prompt(question: str, context: str = "") -> str:
    """
    Build and return a quiz generation prompt string.
    Does NOT call Gemini.
    """
    return QUIZ_PROMPT.format(
        question=question,
        context=context or "No specific content found — use general Kenyan curriculum knowledge.",
    )
