"""
elimu_ai/agents/intent_agent.py

Semantic Intent Agent — replaces pure keyword matching with Gemini-powered
semantic classification.

Capabilities:
  - Detects multiple intents from one query
  - Understands natural language variations ("maths"/"math"/"mathematics")
  - Splits compound queries into independent sub-tasks
  - Falls back to keyword signals when Gemini is unavailable
  - Returns structured IntentResult list with confidence scores
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Concept synonyms (used in prompt context) ─────────────────────────────────
_CONCEPT_MAP = {
    "maths":        "mathematics",
    "math":         "mathematics",
    "math revision":"mathematics revision",
    "kisw":         "kiswahili",
    "swahili":      "kiswahili",
    "bio":          "biology",
    "chem":         "chemistry",
    "phys":         "physics",
    "grade six":    "grade 6",
    "g6":           "grade 6",
    "class six":    "grade 6",
    "primary":      "primary school",
    "schemes":      "schemes of work",
    "scheme":       "schemes of work",
    "sow":          "schemes of work",
    "notes":        "study notes",
    "revision":     "revision materials",
    "exam":         "examination papers",
    "cbc":          "competency based curriculum",
    "kcse":         "kenya certificate of secondary education",
    "pp1":          "pre-primary 1",
    "pp2":          "pre-primary 2",
}

_CLASSIFICATION_PROMPT = """\
You are an AI intent classifier for an educational platform called Elimu AI.
The platform serves Kenyan students, teachers, and parents.

Classify the user's message into one or more of these intents:
  teacher         — explain or teach an educational concept
  quiz            — generate practice questions or tests
  recommendation  — recommend learning materials or resources
  librarian       — find or download specific documents
  community       — create or find forum discussions
  moderation      — report spam or flag content
  catalog         — browse available materials
  search          — find information
  discussion      — start or join a discussion
  general_chat    — greetings or off-topic messages

Rules:
- A query can have MULTIPLE intents. Detect all that apply.
- Each intent must have a confidence score from 0.0 to 1.0.
- Also extract: grade, subject, term, year, doc_type, audience from the query.
- If the query mentions multiple grades/subjects, list ALL of them.
- Normalise synonyms: "maths"→"mathematics", "bio"→"biology", "g6"→"grade6", etc.

Return ONLY valid JSON in this exact format:
{
  "intents": [
    {"name": "recommendation", "confidence": 0.95},
    {"name": "quiz", "confidence": 0.85}
  ],
  "entities": {
    "grades": ["grade4", "grade6"],
    "subjects": ["mathematics", "kiswahili"],
    "terms": ["2"],
    "years": [],
    "doc_types": ["notes", "scheme of work"],
    "audiences": ["student"]
  },
  "sub_queries": [
    {"grade": "grade4", "subject": "mathematics", "term": "2", "doc_type": "notes"},
    {"grade": "grade6", "subject": "kiswahili", "term": "2", "doc_type": "notes"}
  ],
  "reasoning": "User wants notes for two different grades and subjects"
}

User message: {question}
"""


@dataclass
class SemanticIntent:
    name: str
    confidence: float
    matched_signals: List[str] = field(default_factory=list)


@dataclass
class SubQuery:
    """A single decomposed search task from a compound query."""
    grade: Optional[str] = None
    subject: Optional[str] = None
    term: Optional[str] = None
    year: Optional[str] = None
    doc_type: Optional[str] = None
    audience: Optional[str] = None
    original_fragment: str = ""


@dataclass
class IntentAnalysis:
    """Complete semantic analysis of a user query."""
    intents: List[SemanticIntent]
    entities: Dict[str, List[str]]
    sub_queries: List[SubQuery]
    reasoning: str
    used_fallback: bool = False

    @property
    def primary(self) -> str:
        return self.intents[0].name if self.intents else "teacher"

    @property
    def intent_names(self) -> List[str]:
        return [i.name for i in self.intents]


class IntentAgent:
    """
    Semantic intent classification agent.
    Uses Gemini for rich understanding; falls back to keyword signals.
    """

    # Minimum keyword-fallback confidence to skip Gemini classification.
    # Value chosen from the actual signal weights in intent.py:
    #   "schemes of work" → 0.95, "recommend" → 0.90, "quiz me" → 0.95
    # 0.80 means a single strong unambiguous signal already covers the intent.
    _SKIP_GEMINI_CONFIDENCE: float = 0.80
    # Only skip Gemini when exactly ONE intent clears the threshold — compound
    # queries with multiple confident intents still benefit from Gemini.
    _MAX_SINGLE_INTENT_COUNT: int = 1

    def analyse(self, question: str) -> IntentAnalysis:
        """
        Analyse the user's question and return a full IntentAnalysis.
        Never raises — always returns something usable.

        Optimisation: if deterministic keyword routing already produces a
        single high-confidence intent (≥ _SKIP_GEMINI_CONFIDENCE), skip the
        Gemini classification call entirely.  Gemini is only used when:
          - the question is genuinely ambiguous
          - multiple strong intents are present
          - keyword confidence is below the threshold
        """
        if not question or not question.strip():
            return IntentAnalysis(
                intents=[SemanticIntent("teacher", 0.5)],
                entities={},
                sub_queries=[],
                reasoning="Empty query",
            )

        # ── Fast path: deterministic keyword check ─────────────────────────
        keyword_result = self._keyword_fallback(question)
        high_conf = [i for i in keyword_result.intents
                     if i.confidence >= self._SKIP_GEMINI_CONFIDENCE]
        if len(high_conf) == self._MAX_SINGLE_INTENT_COUNT:
            logger.debug(
                "IntentAgent: skipping Gemini — single high-confidence intent "
                "%r (%.2f) from keyword routing",
                high_conf[0].name, high_conf[0].confidence,
            )
            return keyword_result

        # ── Slow path: Gemini semantic classification ──────────────────────
        try:
            result = self._semantic_classify(question)
            if result:
                return result
        except Exception as exc:
            logger.warning("IntentAgent: semantic classification failed: %s", exc)

        # Fallback to keyword signals
        return keyword_result

    def _semantic_classify(self, question: str) -> Optional[IntentAnalysis]:
        """Use Gemini to classify intents semantically."""
        from elimu_ai.gemini import generate

        prompt = _CLASSIFICATION_PROMPT.format(question=question)
        raw = generate(prompt)

        if not raw or raw.startswith("Elimu AI"):
            return None

        # Extract JSON from response
        import re
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            return None

        data = json.loads(match.group())

        intents = [
            SemanticIntent(
                name=i.get("name", "teacher"),
                confidence=float(i.get("confidence", 0.5)),
                matched_signals=["semantic"],
            )
            for i in data.get("intents", [])
        ]

        if not intents:
            return None

        # Sort by confidence
        intents.sort(key=lambda x: x.confidence, reverse=True)

        entities = data.get("entities", {})
        sub_queries = [
            SubQuery(
                grade=sq.get("grade"),
                subject=sq.get("subject"),
                term=sq.get("term"),
                year=sq.get("year"),
                doc_type=sq.get("doc_type"),
                audience=sq.get("audience"),
            )
            for sq in data.get("sub_queries", [])
        ]

        return IntentAnalysis(
            intents=intents,
            entities=entities,
            sub_queries=sub_queries,
            reasoning=data.get("reasoning", ""),
            used_fallback=False,
        )

    def _keyword_fallback(self, question: str) -> IntentAnalysis:
        """Keyword-based fallback when Gemini is unavailable."""
        from elimu_ai.intent import detect_intents
        from elimu_ai.tools.teacher import extract_context_hints

        keyword_intents = detect_intents(question)
        intents = [
            SemanticIntent(
                name=i.name,
                confidence=i.confidence,
                matched_signals=i.matched_signals,
            )
            for i in keyword_intents
        ]

        ctx = extract_context_hints(question)
        entities = {
            "grades":    [ctx["grade"]] if ctx.get("grade") else [],
            "subjects":  [ctx["subject"]] if ctx.get("subject") else [],
            "terms":     [ctx["term"]] if ctx.get("term") else [],
            "years":     [ctx["year"]] if ctx.get("year") else [],
            "doc_types": [],
            "audiences": [ctx["audience"]] if ctx.get("audience") else [],
        }

        sub_queries = []
        if ctx.get("grade") or ctx.get("subject"):
            sub_queries = [SubQuery(
                grade=ctx.get("grade"),
                subject=ctx.get("subject"),
                term=ctx.get("term"),
                year=ctx.get("year"),
                audience=ctx.get("audience"),
            )]

        return IntentAnalysis(
            intents=intents,
            entities=entities,
            sub_queries=sub_queries,
            reasoning="keyword-fallback",
            used_fallback=True,
        )
