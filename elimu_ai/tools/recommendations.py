"""
elimu_ai/tools/recommendations.py

Recommendations tool — surfaces relevant Elimu Library materials.
Responsibilities:
  - recommend(question, ...) → formatted catalog results string

Thin wrapper over library.find_materials() to maintain a stable public API.
"""

from __future__ import annotations

from typing import Optional

from elimu_ai.tools.library import find_materials


def recommend(
    question: str,
    grade: Optional[str] = None,
    subject: Optional[str] = None,
    term: Optional[str] = None,
    year: Optional[str] = None,
    audience: Optional[str] = None,
) -> str:
    """
    Return formatted Elimu Library material recommendations for a query.
    Delegates entirely to find_materials().
    """
    return find_materials(
        question=question,
        grade=grade,
        subject=subject,
        term=term,
        year=year,
        audience=audience,
    )
