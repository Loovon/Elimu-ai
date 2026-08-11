"""
elimu_ai/query_parser.py

Advanced Query Parser — understands compound queries, synonyms, and
multiple grades/subjects/terms in a single message.

Examples:
  "Recommend maths schemes grade 4 term 2 and Kiswahili notes grade 6 term 2"
  → [
      ParsedQuery(grade="grade4", subject="mathematics", term="2", doc_type="schemesofwork"),
      ParsedQuery(grade="grade6", subject="kiswahili",   term="2", doc_type="notes"),
    ]

  "Grade 8 Biology and Chemistry revision"
  → [
      ParsedQuery(grade="grade8", subject="biology",   doc_type="revision"),
      ParsedQuery(grade="grade8", subject="chemistry", doc_type="revision"),
    ]

Rules:
  - No regex-only matching — uses Gemini for disambiguation when possible
  - Understands all common Kenyan curriculum synonyms
  - Always returns at least one ParsedQuery
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Normalisation maps ────────────────────────────────────────────────────────

SUBJECT_SYNONYMS: Dict[str, str] = {
    "maths":           "mathematics",
    "math":            "mathematics",
    "math revision":   "mathematics",
    "kisw":            "kiswahili",
    "swahili":         "kiswahili",
    "bio":             "biology",
    "chem":            "chemistry",
    "phys":            "physics",
    "hist":            "history",
    "geo":             "geography",
    "geog":            "geography",
    "bus":             "businessstudies",
    "business":        "businessstudies",
    "comp":            "computerstudies",
    "agri":            "agricultureandnutrition",
    "agriculture":     "agricultureandnutrition",
    "social":          "socialstudies",
    "integrated":      "integratedscience",
    "environ":         "environmentalactivities",
    "creative":        "creativearts",
    "csl":             "computerstudies",
    "core maths":      "mathematics",
    "core mathematics":"mathematics",
    "essential maths": "mathematics",
}

GRADE_SYNONYMS: Dict[str, str] = {
    "grade six":     "grade6",
    "grade 6":       "grade6",
    "g6":            "grade6",
    "class six":     "grade6",
    "class 6":       "grade6",
    "grade seven":   "grade7",
    "grade 7":       "grade7",
    "g7":            "grade7",
    "grade eight":   "grade8",
    "grade 8":       "grade8",
    "g8":            "grade8",
    "grade nine":    "grade9",
    "grade 9":       "grade9",
    "g9":            "grade9",
    "grade ten":     "grade10",
    "grade 10":      "grade10",
    "g10":           "grade10",
    "form one":      "form1",
    "form 1":        "form1",
    "form two":      "form2",
    "form 2":        "form2",
    "form three":    "form3",
    "form 3":        "form3",
    "form four":     "form4",
    "form 4":        "form4",
    "pp1":           "gradepp1",
    "pp2":           "gradepp2",
    "pre-primary 1": "gradepp1",
    "pre-primary 2": "gradepp2",
    "primary":       "primary",
}

DOC_TYPE_SYNONYMS: Dict[str, str] = {
    "schemes":          "schemesofwork",
    "scheme":           "schemesofwork",
    "schemes of work":  "schemesofwork",
    "scheme of work":   "schemesofwork",
    "sow":              "schemesofwork",
    "lesson plans":     "lessonplan",
    "lesson plan":      "lessonplan",
    "record of work":   "recordofwork",
    "curriculum design":"curriculumdesign",
    "notes":            "notes",
    "revision":         "revision",
    "past papers":      "assessment",
    "past paper":       "assessment",
    "exams":            "assessment",
    "exam":             "assessment",
    "assessment":       "assessment",
    "homework":         "homework",
    "booklet":          "homework",
    "topical":          "assessment",
    "rubrics":          "rubric",
    "rubric":           "rubric",
}

_PARSE_PROMPT = """\
You are an educational query parser for a Kenyan school platform.

Parse this query into separate search tasks. Each task must have:
  grade, subject, term (optional), year (optional), doc_type (optional), audience (optional)

Normalise synonyms:
  "maths" → "mathematics", "kisw" → "kiswahili", "g6" → "grade6",
  "schemes" → "schemesofwork", "notes" → "notes", "revision" → "revision"

Return ONLY valid JSON:
{
  "queries": [
    {"grade": "grade4", "subject": "mathematics", "term": "2", "doc_type": "schemesofwork"},
    {"grade": "grade6", "subject": "kiswahili",   "term": "2", "doc_type": "notes"}
  ]
}

Query: {question}
"""


@dataclass
class ParsedQuery:
    grade: Optional[str] = None
    subject: Optional[str] = None
    term: Optional[str] = None
    year: Optional[str] = None
    doc_type: Optional[str] = None
    audience: Optional[str] = None
    original: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "grade":    self.grade,
            "subject":  self.subject,
            "term":     self.term,
            "year":     self.year,
            "doc_type": self.doc_type,
            "audience": self.audience,
        }


class QueryParser:
    """
    Parses a user query into one or more structured ParsedQuery objects.
    """

    def parse(self, question: str) -> List[ParsedQuery]:
        """
        Parse the question into structured queries.
        Always returns at least one ParsedQuery.

        Optimisation: if deterministic regex parsing already extracts a
        confident result (grade OR subject found, single-target), skip the
        Gemini parse call entirely.  Gemini is only used when:
          - the question contains no clear grade/subject
          - multiple targets are separated by "and" but each part
            is ambiguous (no grade/subject extracted per part)
          - the regex fallback returns only an empty-field query
        """
        if not question or not question.strip():
            return [ParsedQuery(original=question)]

        # ── Fast path: deterministic regex parse ──────────────────────────
        regex_result = self._regex_parse(question)
        # Consider the regex result "confident" when every returned query
        # has at least one concrete field (grade or subject).
        all_confident = all(q.grade or q.subject for q in regex_result)
        if all_confident:
            logger.debug(
                "QueryParser: skipping Gemini — regex produced %d confident "
                "quer%s", len(regex_result),
                "y" if len(regex_result) == 1 else "ies",
            )
            return regex_result

        # ── Slow path: Gemini disambiguation ─────────────────────────────
        try:
            queries = self._gemini_parse(question)
            if queries:
                return queries
        except Exception as exc:
            logger.debug("QueryParser: Gemini parse failed: %s", exc)

        # Use the regex result even if imperfect
        return regex_result

    def _gemini_parse(self, question: str) -> Optional[List[ParsedQuery]]:
        from elimu_ai.gemini import generate
        prompt = _PARSE_PROMPT.format(question=question)
        raw = generate(prompt)
        if not raw or raw.startswith("Elimu AI"):
            return None

        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            return None

        data = json.loads(match.group())
        queries = []
        for q in data.get("queries", []):
            queries.append(ParsedQuery(
                grade=q.get("grade"),
                subject=q.get("subject"),
                term=str(q["term"]) if q.get("term") else None,
                year=str(q["year"]) if q.get("year") else None,
                doc_type=q.get("doc_type"),
                audience=q.get("audience"),
                original=question,
            ))
        return queries if queries else None

    def _regex_parse(self, question: str) -> List[ParsedQuery]:
        """
        Fallback: extract structured info from the question using patterns.
        Returns multiple queries if 'and' separates distinct topics.
        """
        from elimu_ai.catalog_search import _extract_from_keyword

        # Split on "and" to handle compound queries
        parts = re.split(r"\band\b", question, flags=re.IGNORECASE)

        queries = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            grade, subject, term, year = _extract_from_keyword(part)

            # Infer doc_type
            doc_type = None
            part_lower = part.lower()
            for kw, dt in sorted(DOC_TYPE_SYNONYMS.items(), key=lambda x: len(x[0]), reverse=True):
                if kw in part_lower:
                    doc_type = dt
                    break

            # Infer audience
            audience = None
            if any(k in part_lower for k in ("teacher", "scheme", "lesson plan")):
                audience = "teacher"
            elif any(k in part_lower for k in ("student", "revision", "exam")):
                audience = "student"

            queries.append(ParsedQuery(
                grade=grade,
                subject=subject,
                term=term,
                year=year,
                doc_type=doc_type,
                audience=audience,
                original=part,
            ))

        # If nothing found, return a single query for the full question
        if not queries or all(
            not q.grade and not q.subject for q in queries
        ):
            grade, subject, term, year = _extract_from_keyword(question)
            return [ParsedQuery(
                grade=grade, subject=subject,
                term=term, year=year, original=question,
            )]

        return queries


# Module-level convenience instance
query_parser = QueryParser()
