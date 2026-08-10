"""
elimu_ai/orchestrator.py

AI Orchestrator — multi-target query support with per-target deduplication.

Key fix: compound queries like "Maths Grade 2 revision AND Kiswahili Grade 6 schemes"
produce TWO independent retrieval targets that stay separated throughout the pipeline.
The final response is composed once and clearly labelled.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from elimu_ai.intent import detect_intents, IntentResult
from elimu_ai.context_builder import build_context, PromptContext
from elimu_ai.tool_registry import registry
from elimu_ai.qdrant_db import search as qdrant_search
from elimu_ai.helpers import clean_answer, rewrite_links, referral_url
from elimu_ai.tools.teacher import extract_context_hints, extract_context_from_history
from elimu_ai.query_parser import QueryParser, ParsedQuery

logger = logging.getLogger(__name__)

_query_parser = QueryParser()


@dataclass
class TargetResult:
    """Result for a single retrieval target within a compound query."""
    target_label: str          # e.g. "Mathematics — Grade 2"
    grade:        Optional[str]
    subject:      Optional[str]
    doc_type:     Optional[str]
    content:      str
    sources:      List[str] = field(default_factory=list)


@dataclass
class OrchestratorResult:
    request_id:   str
    persona:      str
    answer:       str
    sources:      List[str]
    tools:        List[str]
    intents:      List[IntentResult]
    execution_ms: int = 0
    had_error:    bool = False
    error_detail: str = ""
    tool_outputs: Dict[str, str] = field(default_factory=dict)


def run_orchestrator(
    question: str,
    history: Optional[List[Dict[str, str]]] = None,
    session_id: Optional[str] = None,
    user_id: Optional[int] = None,
    request_id: Optional[str] = None,
) -> OrchestratorResult:
    t_start    = time.monotonic()
    request_id = request_id or str(uuid.uuid4())
    history    = history or []

    logger.info("orchestrator: rid=%s q=%r", request_id[:8], question[:80])

    if not question or not str(question).strip():
        return OrchestratorResult(
            request_id=request_id, persona="teacher",
            answer="Please ask a question and I'll be happy to help!",
            sources=[], tools=[], intents=[],
        )

    # ── Intent detection ──────────────────────────────────────────────────────
    intents      = detect_intents(question)
    intent_names = [i.name for i in intents]
    primary      = intent_names[0] if intent_names else "teacher"
    logger.info("orchestrator: intents=%s", [(i.name, round(i.confidence,2)) for i in intents])

    # ── Compound query parsing ────────────────────────────────────────────────
    targets: List[ParsedQuery] = _query_parser.parse(question)
    logger.info("orchestrator: %d targets parsed", len(targets))

    # ── Context extraction from history ──────────────────────────────────────
    global_hints = extract_context_hints(question)
    if history:
        hist = extract_context_from_history(history[-6:])
        for k in ("grade", "subject", "term", "year", "audience"):
            if not global_hints.get(k) and hist.get(k):
                global_hints[k] = hist[k]

    # ── Qdrant semantic search (one search for overall context) ───────────────
    qdrant_hits: List = []
    try:
        qdrant_hits = qdrant_search(question)
    except Exception as exc:
        logger.warning("orchestrator: Qdrant failed: %s", exc)

    # ── Build shared prompt context ───────────────────────────────────────────
    ctx = build_context(
        question=question,
        persona=primary,
        intents=intent_names,
        history=history,
        curriculum_hints=global_hints,
        qdrant_hits=qdrant_hits,
    )

    tools_used   = ["qdrant_search"]
    had_error    = False
    error_detail = ""
    tool_outputs: Dict[str, str] = {}

    # ── Multi-target retrieval ────────────────────────────────────────────────
    target_results: List[TargetResult] = []
    seen_tool_calls: set = set()  # deduplication: (action, grade, subject)

    is_retrieval_query = any(
        i in intent_names for i in ("librarian", "recommendation", "catalog")
    )

    if is_retrieval_query and len(targets) > 0:
        for tgt in targets:
            dedup_key = (
                "catalog_search",
                (tgt.grade or "").lower(),
                (tgt.subject or "").lower(),
                (tgt.doc_type or "").lower(),
            )
            if dedup_key in seen_tool_calls:
                logger.debug("orchestrator: dedup skipping %s", dedup_key)
                continue
            seen_tool_calls.add(dedup_key)

            try:
                result = _execute_per_target(tgt, question)
                if result:
                    label = _target_label(tgt)
                    target_results.append(TargetResult(
                        target_label=label,
                        grade=tgt.grade,
                        subject=tgt.subject,
                        doc_type=tgt.doc_type,
                        content=result,
                    ))
                    tools_used.append("catalog_search")
            except Exception as exc:
                logger.error("orchestrator: target retrieval failed: %s", exc)
                had_error = True
                error_detail = str(exc)

        if target_results:
            answer = _compose_multi_target(target_results, question)
            answer = clean_answer(answer)
            answer = rewrite_links(answer)
            sources = _extract_sources_from_text(answer)
            execution_ms = int((time.monotonic() - t_start) * 1000)
            _save_analytics(request_id, session_id, user_id, primary,
                            intent_names, tools_used, question, answer,
                            execution_ms, had_error)
            if session_id:
                _update_memory(session_id, question, answer, user_id)
            return OrchestratorResult(
                request_id=request_id, persona=primary, answer=answer,
                sources=sources, tools=tools_used, intents=intents,
                execution_ms=execution_ms, had_error=had_error,
                error_detail=error_detail, tool_outputs=tool_outputs,
            )

    # ── Single-intent tool execution path ────────────────────────────────────
    tools_plan = registry.execution_plan(intent_names)
    logger.info("orchestrator: plan=%s", [t.name for t in tools_plan])

    for tool_def in tools_plan:
        tool_key = (tool_def.name, global_hints.get("grade",""), global_hints.get("subject",""))
        if tool_key in seen_tool_calls:
            logger.debug("orchestrator: dedup skipping tool %s", tool_def.name)
            continue
        seen_tool_calls.add(tool_key)
        try:
            output = tool_def.execute(context=ctx, question=question)
            tool_outputs[tool_def.name] = output or ""
            tools_used.append(tool_def.name)
        except Exception as exc:
            logger.error("orchestrator: tool %r failed: %s", tool_def.name, exc)
            had_error = True
            error_detail = str(exc)
            tool_outputs[tool_def.name] = ""

    answer = _merge_single_outputs(tool_outputs, intents, question)
    answer = clean_answer(answer)
    answer = rewrite_links(answer)
    sources = _extract_sources(qdrant_hits)

    execution_ms = int((time.monotonic() - t_start) * 1000)
    logger.info("orchestrator: done rid=%s ms=%d persona=%s tools=%s",
                request_id[:8], execution_ms, primary, tools_used)

    _save_analytics(request_id, session_id, user_id, primary,
                    intent_names, tools_used, question, answer,
                    execution_ms, had_error)
    if session_id:
        _update_memory(session_id, question, answer, user_id)

    return OrchestratorResult(
        request_id=request_id, persona=primary, answer=answer,
        sources=sources, tools=tools_used, intents=intents,
        execution_ms=execution_ms, had_error=had_error,
        error_detail=error_detail, tool_outputs=tool_outputs,
    )


# ── Per-target retrieval ──────────────────────────────────────────────────────

def _execute_per_target(tgt: ParsedQuery, question: str) -> str:
    """Run catalog+Qdrant retrieval for one specific target."""
    from elimu_ai.tools.library import find_materials
    return find_materials(
        question=tgt.original or question,
        grade=tgt.grade,
        subject=tgt.subject,
        term=tgt.term,
        year=tgt.year,
        audience=tgt.audience,
    )


def _target_label(tgt: ParsedQuery) -> str:
    """Build a human-readable label for a retrieval target."""
    parts = []
    if tgt.subject:
        parts.append(tgt.subject.title())
    if tgt.grade:
        g = tgt.grade
        # normalise grade2 → Grade 2
        import re
        m = re.match(r"grade\s*(\d+|pp\d)", g, re.I)
        if m:
            parts.append(f"Grade {m.group(1).upper()}")
        else:
            parts.append(g.title())
    if tgt.doc_type:
        _DOC_LABELS = {
            "schemesofwork": "Schemes of Work",
            "notes":         "Notes",
            "revision":      "Revision Materials",
            "assessment":    "Exams / Past Papers",
            "lessonplan":    "Lesson Plans",
            "homework":      "Homework",
        }
        parts.append(_DOC_LABELS.get(tgt.doc_type, tgt.doc_type.title()))
    return " — ".join(parts) if parts else tgt.original[:60]


def _compose_multi_target(results: List[TargetResult], question: str) -> str:
    """
    Compose a single coherent answer from multiple retrieval targets.
    Each target gets exactly one clearly labelled section.
    No repetition.
    """
    if not results:
        return "I couldn't find matching materials. Try rephrasing your query."
    if len(results) == 1:
        return results[0].content

    parts = []
    for r in results:
        parts.append(f"{r.target_label}\n\n{r.content}")

    return "\n\n---\n\n".join(parts)


# ── Single-intent merge (unchanged behaviour) ─────────────────────────────────

def _merge_single_outputs(
    tool_outputs: Dict[str, str],
    intents: List[IntentResult],
    question: str,
) -> str:
    clean = {k: v for k, v in tool_outputs.items()
             if v and not k.startswith("_")
             and not (v.startswith("[") and v.endswith("]"))}
    if not clean:
        return "I was unable to generate a response. Please try again."
    if len(clean) == 1:
        return list(clean.values())[0]

    _ORDER = ["teacher", "recommendation", "librarian", "quiz",
              "community", "catalog", "moderation"]
    _LABELS = {
        "teacher": "Explanation", "quiz": "Practice Quiz",
        "librarian": "Materials", "recommendation": "Recommended Materials",
        "community": "Discussion", "catalog": "Catalog Results",
        "moderation": "Content Check",
    }
    ordered = sorted(clean.keys(), key=lambda n: _ORDER.index(n) if n in _ORDER else 99)
    parts   = [f"{_LABELS.get(n, n.title())}\n\n{clean[n]}" for n in ordered]
    return "\n\n---\n\n".join(parts)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fetch_catalog(question: str, hints: Dict) -> str:
    try:
        from elimu_ai.catalog_search import catalog_available, search_catalog, format_recommendations
        if not catalog_available():
            return ""
        results = search_catalog(
            grade=hints.get("grade"), subject=hints.get("subject"),
            term=hints.get("term"), year=hints.get("year"),
            audience=hints.get("audience"), keyword=question, max_results=5,
        )
        return format_recommendations(results, question) if results else ""
    except Exception as exc:
        logger.warning("orchestrator: catalog fetch failed: %s", exc)
        return ""


def _extract_sources(hits: List) -> List[str]:
    sources = []
    for hit in hits:
        try:
            url = (hit.payload or {}).get("url", "")
            if url:
                sources.append(referral_url(url))
        except Exception:
            pass
    return sources


def _extract_sources_from_text(text: str) -> List[str]:
    import re
    urls    = re.findall(r"https?://www\.elimulibrary\.com/site/document/[^\s\)\"']+", text)
    sources = []
    seen    = set()
    for url in urls:
        clean = url.rstrip(".,;:")
        if clean not in seen:
            seen.add(clean)
            sources.append(referral_url(clean))
    return sources


def _merge_outputs(tool_outputs, intents, question):
    """Backward-compat alias for orchestrator tests."""
    return _merge_single_outputs(tool_outputs, intents, question)


def _save_analytics(request_id, session_id, user_id, persona,
                    intents, tools_used, question, answer,
                    execution_ms, had_error) -> None:
    try:
        from elimu_ai.db.repositories import AnalyticsRepository
        AnalyticsRepository().log_request(
            request_id=request_id, user_id=user_id, session_id=session_id,
            persona=persona, intents=intents, tools_used=tools_used,
            question_len=len(question), answer_len=len(answer),
            execution_ms=execution_ms, had_error=had_error,
        )
    except Exception as exc:
        logger.debug("orchestrator: analytics save failed: %s", exc)


def _update_memory(session_id, question, answer, user_id) -> None:
    try:
        from elimu_ai.memory import memory_store
        memory_store.add_turn(session_id, "user", question)
        memory_store.add_turn(session_id, "assistant", answer)
        if memory_store.should_summarise(session_id):
            memory_store.save_summary(session_id, user_id=user_id)
    except Exception as exc:
        logger.debug("orchestrator: memory update failed: %s", exc)
