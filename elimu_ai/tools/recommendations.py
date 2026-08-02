"""
elimu_ai/tools/recommendations.py

Recommendations tool — surfaces relevant Elimu Library materials.
Responsibilities:
  - recommend(question, grade, subject, term, year, audience) → str

Thin wrapper over library.find_materials() that adds a header.
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
    Return a formatted list of recommended Elimu Library materials
    for the given question and optional metadata hints.
    """
    return find_materials(
        question=question,
        grade=grade,
        subject=subject,
        term=term,
        year=year,
        audience=audience,
    )
