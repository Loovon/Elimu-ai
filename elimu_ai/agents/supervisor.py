"""
elimu_ai/agents/supervisor.py

Supervisor Agent — the top-level coordinator of the multi-agent pipeline.

Responsibilities:
  1. Receive question + context
  2. Delegate to IntentAgent for semantic analysis
  3. Delegate to PlannerAgent for execution plan
  4. Delegate to ToolSelectorAgent for tool resolution
  5. Execute tools (parallel where possible, sequential otherwise)
  6. Delegate to VerifierAgent for output quality check
  7. Retry on failure (up to MAX_RETRIES)
  8. Delegate to LearningAgent for recording outcomes
  9. Return structured SupervisorResult

The supervisor NEVER hallucinates — all URLs come from tools.
The supervisor NEVER crashes — it always returns a usable result.
"""

from __future__ import annotations

import concurrent.futures
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from elimu_ai.agents.intent_agent import IntentAgent, IntentAnalysis
from elimu_ai.agents.planner import PlannerAgent, ExecutionPlan, PlanStep
from elimu_ai.agents.tool_selector import ToolSelectorAgent
from elimu_ai.agents.verifier import VerifierAgent, VerificationResult
from elimu_ai.agents.learning import LearningAgent

logger = logging.getLogger(__name__)

MAX_RETRIES = 2
MAX_PARALLEL_TOOLS = 5


@dataclass
class SupervisorResult:
    """Final structured result from the supervisor pipeline."""
    request_id: str
    question: str
    answer: str
    persona: str
    intents: List[str]
    tools_used: List[str]
    sources: List[str]
    execution_ms: int
    verification: Optional[VerificationResult] = None
    plan: Optional[ExecutionPlan] = None
    had_error: bool = False
    error_detail: str = ""
    tool_outputs: Dict[str, str] = field(default_factory=dict)
    sub_query_results: List[Dict[str, Any]] = field(default_factory=list)


class SupervisorAgent:
    """
    Autonomous supervisor that coordinates the full agent pipeline.
    """

    def __init__(self) -> None:
        self.intent_agent   = IntentAgent()
        self.planner        = PlannerAgent()
        self.tool_selector  = ToolSelectorAgent()
        self.verifier       = VerifierAgent()
        self.learner        = LearningAgent()

    def run(
        self,
        question: str,
        history: Optional[List[Dict[str, str]]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[int] = None,
        request_id: Optional[str] = None,
    ) -> SupervisorResult:
        """
        Execute the full autonomous agent pipeline.
        Never raises. Always returns a SupervisorResult.
        """
        t_start    = time.monotonic()
        request_id = request_id or str(uuid.uuid4())
        history    = history or []

        logger.info(
            "Supervisor: request_id=%s question=%r session=%s",
            request_id[:8], question[:80], session_id,
        )

        if not question or not str(question).strip():
            return self._empty_result(request_id)

        # ── Phase 1: Semantic Intent Analysis ────────────────────────────
        analysis: IntentAnalysis = self.intent_agent.analyse(question)
        logger.info(
            "Supervisor: intents=%s sub_queries=%d",
            analysis.intent_names, len(analysis.sub_queries),
        )

        # ── Phase 2: Execution Plan ───────────────────────────────────────
        plan: ExecutionPlan = self.planner.plan(analysis, question)
        logger.info(
            "Supervisor: plan=%d steps, tools=%s",
            len(plan.steps), plan.estimated_tools,
        )

        # ── Log agent decision (non-fatal) ────────────────────────────────
        self._log_decision(
            request_id=request_id,
            session_id=session_id,
            user_id=user_id,
            question=question,
            analysis=analysis,
            plan=plan,
        )

        # ── Phase 3: Build context ────────────────────────────────────────
        ctx = self._build_context(question, analysis, history,
                                  session_id=session_id, user_id=user_id)

        # ── Phase 4: Execute with retry ───────────────────────────────────
        tool_outputs: Dict[str, str] = {}
        sub_results: List[Dict[str, Any]] = []
        tools_used: List[str] = []
        had_error = False
        error_detail = ""

        for attempt in range(MAX_RETRIES + 1):
            try:
                tool_outputs, sub_results, tools_used = self._execute_plan(
                    plan, ctx, question, analysis
                )
                break
            except Exception as exc:
                had_error = True
                error_detail = str(exc)
                logger.error(
                    "Supervisor: attempt %d/%d failed: %s",
                    attempt + 1, MAX_RETRIES + 1, exc, exc_info=True,
                )
                if attempt < MAX_RETRIES:
                    logger.info("Supervisor: retrying…")
                    time.sleep(1.0 * (attempt + 1))

        # ── Phase 5: Merge outputs ────────────────────────────────────────
        from elimu_ai.natural_language import NaturalLanguageWriter
        raw_answer = self._merge_outputs(
            tool_outputs, sub_results, analysis, question
        )

        # ── Phase 6: Natural language rewrite ────────────────────────────
        writer = NaturalLanguageWriter()
        answer = writer.rewrite(
            raw=raw_answer,
            persona=analysis.primary,
            question=question,
        )

        # ── Phase 7: Verify ───────────────────────────────────────────────
        sources = self._collect_sources(tool_outputs)
        verification = self.verifier.verify(answer, question, sources)
        if not verification.passed:
            logger.warning(
                "Supervisor: verification failed — issues=%s", verification.issues
            )
            had_error = True
            if verification.revised_answer:
                answer = verification.revised_answer
            self.learner.record_hallucination(
                question=question,
                answer=answer,
                issues=verification.issues,
                confidence=verification.confidence,
                user_id=user_id,
            )
        elif verification.revised_answer:
            answer = verification.revised_answer

        # ── Phase 8: Add referral links ───────────────────────────────────
        from elimu_ai.helpers import rewrite_links
        answer = rewrite_links(answer)

        execution_ms = int((time.monotonic() - t_start) * 1000)

        # ── Phase 9: Learn ────────────────────────────────────────────────
        if had_error or not verification.passed:
            self.learner.record_failure(
                question=question,
                intents=analysis.intent_names,
                tools_used=tools_used,
                failure_reason=error_detail or "; ".join(verification.issues),
                user_id=user_id,
                session_id=session_id,
                suggested_fix="Review tool selection and retry.",
            )
        else:
            self.learner.record_success(
                question=question,
                intents=analysis.intent_names,
                tools_used=tools_used,
                persona=analysis.primary,
                execution_ms=execution_ms,
                user_id=user_id,
                session_id=session_id,
            )

        # ── Phase 10: Memory + Analytics ─────────────────────────────────
        self._save_analytics(
            request_id, session_id, user_id, analysis, tools_used,
            question, answer, execution_ms, had_error,
        )
        if session_id:
            self._update_memory(session_id, question, answer, user_id)

        logger.info(
            "Supervisor: done request_id=%s ms=%d persona=%s tools=%s",
            request_id[:8], execution_ms, analysis.primary, tools_used,
        )

        return SupervisorResult(
            request_id=request_id,
            question=question,
            answer=answer,
            persona=analysis.primary,
            intents=analysis.intent_names,
            tools_used=tools_used,
            sources=sources,
            execution_ms=execution_ms,
            verification=verification,
            plan=plan,
            had_error=had_error,
            error_detail=error_detail,
            tool_outputs=tool_outputs,
            sub_query_results=sub_results,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _empty_result(self, request_id: str) -> SupervisorResult:
        return SupervisorResult(
            request_id=request_id,
            question="",
            answer="Please ask a question and I'll be happy to help!",
            persona="teacher",
            intents=[],
            tools_used=[],
            sources=[],
            execution_ms=0,
        )

    def _build_context(
        self,
        question: str,
        analysis: IntentAnalysis,
        history: List[Dict],
        session_id: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Any:
        """Build the PromptContext for tool execution."""
        from elimu_ai.context_builder import build_context
        from elimu_ai.tools.teacher import extract_context_hints, extract_context_from_history
        from elimu_ai.qdrant_db import search as qdrant_search

        # Restore prior session context if the worker just started
        if session_id:
            try:
                from elimu_ai.memory import memory_store
                memory_store.restore_session(session_id, user_id=user_id)
            except Exception as exc:
                logger.debug("Supervisor: session restore failed (non-fatal): %s", exc)

        ctx_hints = extract_context_hints(question)
        if history:
            hist = extract_context_from_history(history[-6:])
            for k in ("grade", "subject", "term", "year", "audience"):
                if not ctx_hints.get(k) and hist.get(k):
                    ctx_hints[k] = hist[k]

        # Merge entities from semantic analysis
        entities = analysis.entities
        if not ctx_hints.get("grade") and entities.get("grades"):
            ctx_hints["grade"] = entities["grades"][0]
        if not ctx_hints.get("subject") and entities.get("subjects"):
            ctx_hints["subject"] = entities["subjects"][0]

        # Catalog-only requests do not need a semantic context search. Skipping
        # it avoids an unnecessary embedding call and lets the local catalog
        # remain usable while Qdrant collections are being migrated.
        hits = []
        retrieval_intents = {"teacher", "quiz", "search"}
        if not analysis.intent_names or retrieval_intents.intersection(analysis.intent_names):
            try:
                hits = qdrant_search(question)
            except Exception:
                pass

        return build_context(
            question=question,
            persona=analysis.primary,
            intents=analysis.intent_names,
            history=history,
            curriculum_hints=ctx_hints,
            qdrant_hits=hits,
        )

    def _execute_plan(
        self,
        plan: ExecutionPlan,
        ctx: Any,
        question: str,
        analysis: IntentAnalysis,
    ):
        """Execute the plan steps, respecting dependencies and parallelism."""
        tool_outputs: Dict[str, str] = {}
        sub_results: List[Dict[str, Any]] = []
        tools_used: List[str] = []

        # Group steps by dependency wave
        completed: set = set()

        def wave_ready(step: PlanStep) -> bool:
            return all(d in completed for d in step.depends_on)

        remaining = list(plan.steps)

        while remaining:
            # Collect steps that are ready
            ready = [s for s in remaining if wave_ready(s)]
            if not ready:
                # Prevent infinite loop
                break

            # Partition into parallel and sequential
            parallel_steps = [s for s in ready if s.parallel and s.action not in {
                "_merge_results", "_verify_output", "_generate_response",
                "_store_analytics", "_store_memory", "_learn",
            }]
            sequential_steps = [s for s in ready if not s.parallel or s.action in {
                "_merge_results", "_verify_output", "_generate_response",
                "_store_analytics", "_store_memory", "_learn",
            }]

            # Execute parallel steps concurrently
            if parallel_steps:
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=min(MAX_PARALLEL_TOOLS, len(parallel_steps))
                ) as ex:
                    futures = {
                        ex.submit(
                            self._execute_step, step, ctx, question, analysis
                        ): step
                        for step in parallel_steps[:MAX_PARALLEL_TOOLS]
                    }
                    for future in concurrent.futures.as_completed(futures, timeout=60):
                        step = futures[future]
                        try:
                            result = future.result()
                            if result:
                                output_key = step.action
                                if output_key in tool_outputs:
                                    output_key = f"{step.action}_{step.step_id}"
                                tool_outputs[output_key] = result
                                if not step.action.startswith("_"):
                                    tools_used.append(step.action)
                                    sub_results.append({
                                        "step_id": step.step_id,
                                        "action":  step.action,
                                        "result":  result[:300],
                                        "params":  step.params,
                                    })
                        except Exception as exc:
                            logger.error(
                                "Supervisor: parallel step %r failed: %s",
                                step.action, exc,
                            )
                        completed.add(step.step_id)

            # Execute sequential steps
            for step in sequential_steps:
                try:
                    result = self._execute_step(step, ctx, question, analysis)
                    if result:
                        output_key = step.action
                        if output_key in tool_outputs:
                            output_key = f"{step.action}_{step.step_id}"
                        tool_outputs[output_key] = result
                        if not step.action.startswith("_"):
                            tools_used.append(step.action)
                except Exception as exc:
                    logger.error(
                        "Supervisor: sequential step %r failed: %s",
                        step.action, exc,
                    )
                completed.add(step.step_id)

            remaining = [s for s in remaining if s.step_id not in completed]

        return tool_outputs, sub_results, tools_used

    def _execute_step(
        self,
        step: PlanStep,
        ctx: Any,
        question: str,
        analysis: IntentAnalysis,
    ) -> Optional[str]:
        """Execute a single plan step."""
        action = step.action

        # System actions — handled inline
        if action.startswith("_"):
            return None  # handled in merge/verify/respond phases

        # Tool actions
        fn = self.tool_selector.select(action, step.params)
        if fn is None:
            return None

        params = step.params

        # Catalog search: use structured params from sub-query
        if action == "catalog_search":
            from elimu_ai.catalog_search import search_catalog, format_recommendations
            results = search_catalog(
                grade=params.get("grade"),
                subject=params.get("subject"),
                term=params.get("term"),
                year=params.get("year"),
                doctype=params.get("doc_type"),
                audience=params.get("audience"),
                keyword=params.get("question", question),
                max_results=5,
            )
            if results:
                return format_recommendations(results, question)
            from elimu_ai.tools.library import _category_fallback
            return _category_fallback(
                {
                    "grade": params.get("grade"),
                    "subject": params.get("subject"),
                    "audience": params.get("audience"),
                },
                params.get("doc_type") or "",
                params.get("question", question),
            )

        # Qdrant search
        if action == "qdrant_search":
            hits = fn(params.get("question", question))
            if not hits:
                return ""
            from elimu_ai.context_builder import _format_qdrant_hits
            return _format_qdrant_hits(hits)

        # Forum search
        if action == "forum_search":
            result = fn(params.get("question", question))
            return result or ""

        # Tool registry tools (teacher, quiz, etc.)
        try:
            return fn(context=ctx, question=params.get("question", question))
        except TypeError:
            return fn(params.get("question", question))

    def _merge_outputs(
        self,
        tool_outputs: Dict[str, str],
        sub_results: List[Dict[str, Any]],
        analysis: IntentAnalysis,
        question: str,
    ) -> str:
        """Merge all tool outputs into a coherent response."""
        clean = {
            k: v for k, v in tool_outputs.items()
            if v and not k.startswith("_") and not v.startswith("[")
        }

        if not clean:
            return "I wasn't able to find information on that. Please try rephrasing your question."

        clean_values = _deduplicate_output_blocks(list(clean.values()))
        if len(clean_values) == 1:
            return clean_values[0]

        # Order: teacher/quiz → recommendation/librarian → community → catalog
        order = ["teacher", "quiz", "recommendation", "librarian",
                 "community", "moderation", "catalog"]
        parts = []
        consumed = set()
        for name in order:
            for key, value in clean.items():
                if key == name or key.startswith(name + "_"):
                    parts.extend(_deduplicate_output_blocks([value]))
                    consumed.add(key)
        # Add anything not in the order list
        for name, val in clean.items():
            if name not in consumed:
                parts.extend(_deduplicate_output_blocks([val]))

        return "\n\n".join(parts)

    def _collect_sources(self, tool_outputs: Dict[str, str]) -> List[str]:
        """Extract URLs from tool outputs as source references."""
        from elimu_ai.helpers import referral_url
        import re
        sources = []
        seen = set()
        for text in tool_outputs.values():
            urls = re.findall(r"https?://www\.elimulibrary\.com/site/document/[^\s\)\"']+", text)
            for url in urls:
                clean = url.rstrip(".,;:")
                if clean not in seen:
                    seen.add(clean)
                    sources.append(referral_url(clean))
        return sources

    def _save_analytics(
        self,
        request_id, session_id, user_id,
        analysis, tools_used, question, answer,
        execution_ms, had_error,
    ) -> None:
        try:
            from elimu_ai.db.repositories import AnalyticsRepository
            AnalyticsRepository().log_request(
                request_id=request_id,
                user_id=user_id,
                persona=analysis.primary,
                intents=analysis.intent_names,
                tools_used=tools_used,
                question_len=len(question),
                answer_len=len(answer),
                execution_ms=execution_ms,
                had_error=had_error,
                session_id=session_id,
            )
        except Exception as exc:
            logger.debug("Supervisor analytics: %s", exc)

    def _log_decision(
        self,
        request_id: str,
        session_id: Optional[str],
        user_id: Optional[int],
        question: str,
        analysis: "IntentAnalysis",
        plan: "ExecutionPlan",
        confidence: float = 0.0,
        had_error: bool = False,
        execution_ms: int = 0,
    ) -> None:
        """
        Persist the agent decision to ai_agent_decisions.
        Non-fatal — never raises, never crashes the request pipeline.
        """
        try:
            from elimu_ai.db.repositories import AgentLogRepository
            top_conf = analysis.intents[0].confidence if analysis.intents else 0.0
            AgentLogRepository().log_decision(
                request_id=request_id,
                session_id=session_id,
                user_id=user_id,
                question=question,
                intents=analysis.intent_names,
                plan_steps=[s.action for s in plan.steps],
                tools_used=plan.estimated_tools,
                persona=analysis.primary,
                confidence=top_conf,
                execution_ms=execution_ms,
                had_error=had_error,
            )
        except Exception as exc:
            logger.debug("Supervisor log_decision: %s", exc)

    def _update_memory(
        self,
        session_id: str,
        question: str,
        answer: str,
        user_id: Optional[int],
    ) -> None:
        try:
            from elimu_ai.memory import memory_store
            memory_store.add_turn(session_id, "user", question)
            memory_store.add_turn(session_id, "assistant", answer)
            if memory_store.should_summarise(session_id):
                memory_store.save_summary(session_id, user_id=user_id)
        except Exception as exc:
            logger.debug("Supervisor memory: %s", exc)


def _deduplicate_output_blocks(values: List[str]) -> List[str]:
    """Remove repeated full tool outputs while preserving retrieval order."""
    unique: List[str] = []
    seen = set()
    for value in values:
        normalized = " ".join((value or "").split()).lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(value)
    return unique
