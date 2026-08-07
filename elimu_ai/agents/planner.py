"""
elimu_ai/agents/planner.py

Planning Agent — generates a structured execution plan from IntentAnalysis.

Given intents and sub-queries, produces an ordered list of PlanStep objects
that tell the tool selector and supervisor exactly what to do.

Example plan for "Recommend Grade 4 Maths notes and quiz me on biology":
  Step 1: catalog_search (grade=grade4, subject=mathematics, doc_type=notes)
  Step 2: catalog_search (subject=biology)
  Step 3: quiz_generate  (subject=biology)
  Step 4: merge_results
  Step 5: generate_response
  Step 6: store_analytics
  Step 7: store_memory
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from elimu_ai.agents.intent_agent import IntentAnalysis, SubQuery

logger = logging.getLogger(__name__)


@dataclass
class PlanStep:
    """A single step in the execution plan."""
    step_id: int
    action: str              # tool name or system action
    params: Dict[str, Any]   # parameters for the action
    depends_on: List[int] = field(default_factory=list)  # step IDs this depends on
    parallel: bool = False   # can run in parallel with sibling steps
    retries: int = 2         # retry count on failure
    timeout_seconds: int = 30


@dataclass
class ExecutionPlan:
    """Ordered sequence of plan steps."""
    steps: List[PlanStep]
    reasoning: str
    estimated_tools: List[str]

    @property
    def tool_names(self) -> List[str]:
        return [s.action for s in self.steps
                if not s.action.startswith("_")]


# ── Action constants ──────────────────────────────────────────────────────────
_SYSTEM_ACTIONS = {
    "_merge_results", "_generate_response", "_store_analytics",
    "_store_memory", "_verify_output", "_learn",
}


class PlannerAgent:
    """
    Generates an execution plan from an IntentAnalysis.
    Pure logic — no Gemini calls, no DB, no side effects.
    """

    def plan(self, analysis: IntentAnalysis, question: str) -> ExecutionPlan:
        """
        Build an execution plan from the intent analysis.
        Always produces a valid plan even if intents are ambiguous.
        """
        steps: List[PlanStep] = []
        step_id = 1

        # ── Phase 1: Data retrieval steps (can run in parallel) ───────────
        retrieval_ids: List[int] = []

        for sq in analysis.sub_queries:
            action = self._action_for_sub_query(sq, analysis.intent_names)
            steps.append(PlanStep(
                step_id=step_id,
                action=action,
                params=self._params_from_sub_query(sq, question),
                parallel=True,
                retries=2,
                timeout_seconds=20,
            ))
            retrieval_ids.append(step_id)
            step_id += 1

        # If no sub_queries, generate retrieval steps from intents
        if not analysis.sub_queries:
            for intent in analysis.intents:
                action = self._action_for_intent(intent.name)
                if action:
                    steps.append(PlanStep(
                        step_id=step_id,
                        action=action,
                        params={"question": question},
                        parallel=True,
                        retries=2,
                        timeout_seconds=20,
                    ))
                    retrieval_ids.append(step_id)
                    step_id += 1

        # ── Phase 2: Generation steps (depend on retrieval) ──────────────
        gen_ids: List[int] = []
        for intent in analysis.intents:
            gen_action = self._generation_action(intent.name)
            if gen_action and gen_action not in [s.action for s in steps]:
                steps.append(PlanStep(
                    step_id=step_id,
                    action=gen_action,
                    params={"question": question},
                    depends_on=retrieval_ids.copy(),
                    retries=3,
                    timeout_seconds=30,
                ))
                gen_ids.append(step_id)
                step_id += 1

        # ── Phase 3: Merge + Respond ─────────────────────────────────────
        merge_step_id = step_id
        steps.append(PlanStep(
            step_id=merge_step_id,
            action="_merge_results",
            params={},
            depends_on=(retrieval_ids + gen_ids) if gen_ids else retrieval_ids,
        ))
        step_id += 1

        # ── Phase 4: Verify ───────────────────────────────────────────────
        verify_step_id = step_id
        steps.append(PlanStep(
            step_id=verify_step_id,
            action="_verify_output",
            params={},
            depends_on=[merge_step_id],
        ))
        step_id += 1

        # ── Phase 5: Generate natural response ───────────────────────────
        response_step_id = step_id
        steps.append(PlanStep(
            step_id=response_step_id,
            action="_generate_response",
            params={"question": question},
            depends_on=[verify_step_id],
        ))
        step_id += 1

        # ── Phase 6: Store + Learn ────────────────────────────────────────
        steps.append(PlanStep(
            step_id=step_id,
            action="_store_analytics",
            params={},
            depends_on=[response_step_id],
            timeout_seconds=5,
        ))
        step_id += 1
        steps.append(PlanStep(
            step_id=step_id,
            action="_store_memory",
            params={},
            depends_on=[response_step_id],
            timeout_seconds=5,
        ))
        step_id += 1
        steps.append(PlanStep(
            step_id=step_id,
            action="_learn",
            params={},
            depends_on=[response_step_id],
            timeout_seconds=5,
        ))

        tool_names = [s.action for s in steps if s.action not in _SYSTEM_ACTIONS]

        logger.info(
            "PlannerAgent: generated %d-step plan for intents=%s",
            len(steps), analysis.intent_names,
        )

        return ExecutionPlan(
            steps=steps,
            reasoning=analysis.reasoning,
            estimated_tools=tool_names,
        )

    # ── Mapping helpers ───────────────────────────────────────────────────────

    def _action_for_sub_query(self, sq: SubQuery, intents: List[str]) -> str:
        """Determine the retrieval action for a specific sub-query."""
        if "quiz" in intents:
            return "qdrant_search"
        if sq.doc_type and any(
            kw in (sq.doc_type or "")
            for kw in ("scheme", "lesson plan", "record", "curriculum", "notes")
        ):
            return "catalog_search"
        if "recommendation" in intents or "librarian" in intents:
            return "catalog_search"
        return "qdrant_search"

    def _params_from_sub_query(self, sq: SubQuery, question: str) -> Dict[str, Any]:
        return {
            "grade":    sq.grade,
            "subject":  sq.subject,
            "term":     sq.term,
            "year":     sq.year,
            "doc_type": sq.doc_type,
            "audience": sq.audience,
            "question": question,
        }

    def _action_for_intent(self, intent: str) -> Optional[str]:
        return {
            "teacher":        "qdrant_search",
            "quiz":           "qdrant_search",
            "librarian":      "catalog_search",
            "recommendation": "catalog_search",
            "community":      "forum_search",
            "catalog":        "catalog_search",
            "search":         "qdrant_search",
            "moderation":     None,
            "discussion":     "forum_search",
            "general_chat":   None,
        }.get(intent)

    def _generation_action(self, intent: str) -> Optional[str]:
        return {
            "teacher":        "teacher",
            "quiz":           "quiz",
            "librarian":      "librarian",
            "recommendation": "recommendation",
            "community":      "community",
            "moderation":     "moderation",
            "discussion":     "community",
            "general_chat":   "teacher",
        }.get(intent)
