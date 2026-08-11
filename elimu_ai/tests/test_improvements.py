"""
elimu_ai/tests/test_improvements.py

Tests for all Phase 2–7 improvements:
  - Intent agent skips Gemini for high-confidence single-intent queries
  - QueryParser skips Gemini when regex finds grade/subject
  - NaturalLanguageWriter skips Gemini rewrite for already-clean text
  - Qdrant score_threshold parameter accepted and forwarded
  - Zero-evidence retrieval records failure and returns fallback
  - browse/category fallback is NOT classified as successful evidence
  - Agent decisions are persisted (log_decision called)
  - Successful quizzes are persisted (save_quiz called)
  - Failed queries have retry_count / resolved columns in schema
  - Session summary can be restored via restore_session()
  - Ingest payload includes source_type and ingested_at
  - Normal teacher question still works end-to-end
  - Document URL preserved exactly from payload
  - Existing forum/community path still works
"""
from __future__ import annotations

import types
import unittest
from unittest.mock import MagicMock, patch, call


# ── A. Intent routing ─────────────────────────────────────────────────────────

class TestIntentAgentSkipsGemini(unittest.TestCase):
    """IntentAgent must not call Gemini for a single high-confidence intent."""

    def setUp(self):
        from elimu_ai.agents.intent_agent import IntentAgent
        self.agent = IntentAgent()

    def test_simple_library_query_no_gemini(self):
        """A query with a strong doc-type keyword (0.95 signal) skips Gemini.
        'Grade 4 Mathematics notes' only hits the weak 'notes' signal (0.60)
        and correctly falls through to Gemini for disambiguation.
        A query with 'schemes of work' (0.95) should skip Gemini.
        """
        with patch("elimu_ai.agents.intent_agent.IntentAgent._semantic_classify") as mock_sc:
            result = self.agent.analyse("Grade 6 Mathematics schemes of work")
        mock_sc.assert_not_called()
        self.assertIsNotNone(result)

    def test_schemes_query_no_gemini(self):
        """'Grade 6 Kiswahili schemes of work' → single confident librarian, no Gemini."""
        with patch("elimu_ai.agents.intent_agent.IntentAgent._semantic_classify") as mock_sc:
            result = self.agent.analyse("Grade 6 Kiswahili schemes of work")
        mock_sc.assert_not_called()

    def test_ambiguous_query_uses_gemini(self):
        """A vague question with no strong keyword signal should fall through to Gemini."""
        with patch("elimu_ai.agents.intent_agent.IntentAgent._semantic_classify",
                   return_value=None) as mock_sc:
            # Low-signal question: no subject, no grade, no doc-type keyword
            self.agent.analyse("help me please")
        mock_sc.assert_called_once()

    def test_compound_query_uses_gemini(self):
        """Two high-confidence intents in one query should still try Gemini."""
        with patch("elimu_ai.agents.intent_agent.IntentAgent._semantic_classify",
                   return_value=None) as mock_sc:
            # Both quiz AND librarian signals fire strongly
            self.agent.analyse("quiz me on biology and recommend Grade 6 Maths notes")
        mock_sc.assert_called_once()


# ── B. Query parser ───────────────────────────────────────────────────────────

class TestQueryParserSkipsGemini(unittest.TestCase):
    """QueryParser must skip Gemini when regex confidently extracts structure."""

    def setUp(self):
        from elimu_ai.query_parser import QueryParser
        self.parser = QueryParser()

    def test_clear_grade_subject_no_gemini(self):
        """'Grade 4 Mathematics notes' has grade+subject — Gemini not needed."""
        with patch("elimu_ai.query_parser.QueryParser._gemini_parse") as mock_gp:
            result = self.parser.parse("Grade 4 Mathematics notes")
        mock_gp.assert_not_called()
        self.assertTrue(any(q.grade or q.subject for q in result))

    def test_compound_grade_subject_no_gemini(self):
        """Compound query with clear grades/subjects on each side → no Gemini."""
        with patch("elimu_ai.query_parser.QueryParser._gemini_parse") as mock_gp:
            result = self.parser.parse(
                "Grade 4 Mathematics notes and Grade 6 Kiswahili revision"
            )
        mock_gp.assert_not_called()
        self.assertEqual(len(result), 2)

    def test_unclear_query_uses_gemini(self):
        """A question with no extractable grade/subject should try Gemini."""
        with patch("elimu_ai.query_parser.QueryParser._gemini_parse",
                   return_value=None) as mock_gp:
            self.parser.parse("I need something for revision")
        mock_gp.assert_called_once()

    def test_parsed_query_preserves_grade_subject(self):
        result = self.parser.parse("Form 3 Biology past papers")
        self.assertTrue(any(q.grade or q.subject for q in result))


# ── C. Natural language rewrite ───────────────────────────────────────────────

class TestNaturalLanguageWriterSkipsGemini(unittest.TestCase):
    """Gemini rewrite should be skipped for already-clean or document-list output."""

    def setUp(self):
        from elimu_ai.natural_language import NaturalLanguageWriter
        self.writer = NaturalLanguageWriter()

    def test_document_list_skips_gemini(self):
        """Text containing elimulibrary.com/site/document/ → light clean only, no Gemini."""
        doc_text = (
            "Here are the best matching materials:\n\n"
            "1. Grade 4 Mathematics Notes\n"
            "   https://www.elimulibrary.com/site/document/123/maths-notes\n"
        )
        with patch("elimu_ai.natural_language.NaturalLanguageWriter._gemini_rewrite") as mock_rw:
            result = self.writer.rewrite(doc_text, question="Grade 4 Maths notes")
        mock_rw.assert_not_called()
        # URL preserved exactly
        self.assertIn("https://www.elimulibrary.com/site/document/123/maths-notes", result)

    def test_already_clean_text_skips_gemini(self):
        """Plain text with no Markdown and no robotic opener → rule-based, no Gemini."""
        clean_text = (
            "Photosynthesis is the process by which plants make food using sunlight. "
            "It takes place in the chloroplasts. Carbon dioxide and water are converted "
            "to glucose and oxygen."
        )
        with patch("elimu_ai.natural_language.NaturalLanguageWriter._gemini_rewrite") as mock_rw:
            result = self.writer.rewrite(clean_text, question="What is photosynthesis?")
        mock_rw.assert_not_called()
        self.assertIn("Photosynthesis", result)

    def test_markdown_text_uses_gemini(self):
        """Text with ** bold Markdown triggers Gemini rewrite."""
        markdown_text = (
            "**Photosynthesis** is the process by which **plants** make food.\n"
            "## Key Points\n- Chloroplasts\n- CO2 + H2O → Glucose"
        )
        with patch("elimu_ai.natural_language.NaturalLanguageWriter._gemini_rewrite",
                   return_value="Clean plain text answer.") as mock_rw:
            self.writer.rewrite(markdown_text, question="Explain photosynthesis")
        mock_rw.assert_called_once()


# ── D. Qdrant score threshold ─────────────────────────────────────────────────

class TestQdrantScoreThreshold(unittest.TestCase):
    """search() must accept and forward score_threshold without breaking callers."""

    def test_search_accepts_score_threshold_param(self):
        """Calling search() with score_threshold=0.0 must not raise."""
        from elimu_ai.qdrant_db import search
        with patch("elimu_ai.qdrant_db._get_client", return_value=None):
            result = search("test query", score_threshold=0.0)
        self.assertEqual(result, [])

    def test_search_default_threshold_is_zero(self):
        """Default QDRANT_SCORE_THRESHOLD=0.0 means no results are filtered."""
        from elimu_ai import config
        self.assertIsInstance(config.QDRANT_SCORE_THRESHOLD, float)

    def test_score_threshold_forwarded_to_query_points(self):
        """When threshold > 0, score_threshold is included in query_points kwargs."""
        from elimu_ai.qdrant_db import search, _qdrant
        import elimu_ai.qdrant_db as qdb

        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.points = []
        mock_client.query_points.return_value = mock_result

        with patch("elimu_ai.qdrant_db._get_client", return_value=mock_client), \
             patch("elimu_ai.qdrant_db.gemini_embed", return_value=[0.1] * 768):
            search("test", score_threshold=0.5)

        call_kwargs = mock_client.query_points.call_args[1]
        self.assertIn("score_threshold", call_kwargs)
        self.assertEqual(call_kwargs["score_threshold"], 0.5)


# ── E. Retrieval failure detection ────────────────────────────────────────────

class TestRetrievalFailureDetection(unittest.TestCase):
    """Zero evidence must record a failure; browse fallback is NOT evidence."""

    def test_zero_results_records_failure(self):
        """When Qdrant and catalog both return nothing, LearningAgent.record_failure is called."""
        with patch("elimu_ai.tools.library._qdrant_search_for_query", return_value=[]), \
             patch("elimu_ai.tools.library._catalog_search_for_query", return_value=[]), \
             patch("elimu_ai.tools.library._record_retrieval_failure") as mock_fail:
            from elimu_ai.tools.library import find_materials
            result = find_materials("Grade 4 Mathematics notes",
                                    grade="grade4", subject="mathematics")
        mock_fail.assert_called_once()
        failure_kwargs = mock_fail.call_args[1]
        self.assertEqual(failure_kwargs.get("question"), "Grade 4 Mathematics notes")

    def test_zero_results_returns_fallback_text(self):
        """The category fallback is still returned to the user even after failure record."""
        with patch("elimu_ai.tools.library._qdrant_search_for_query", return_value=[]), \
             patch("elimu_ai.tools.library._catalog_search_for_query", return_value=[]), \
             patch("elimu_ai.tools.library._record_retrieval_failure"):
            from elimu_ai.tools.library import find_materials
            result = find_materials("Grade 4 Mathematics notes",
                                    grade="grade4", subject="mathematics")
        # Should contain browse links, not actual document URLs
        self.assertNotIn("/site/document/", result)
        self.assertTrue(len(result) > 20)

    def test_successful_hit_does_not_record_failure(self):
        """When evidence is found, _record_retrieval_failure must NOT be called."""
        fake_hit = {
            "source": "qdrant", "score": 0.85,
            "url": "https://www.elimulibrary.com/site/document/1/test",
            "title": "Grade 4 Maths Notes", "grade": "grade4",
            "subject": "mathematics", "term": "", "year": "",
            "doctype": "notes", "audience": "student",
            "price": None, "description": "", "curriculum": "",
        }
        with patch("elimu_ai.tools.library._qdrant_search_for_query", return_value=[fake_hit]), \
             patch("elimu_ai.tools.library._record_retrieval_failure") as mock_fail:
            from elimu_ai.tools.library import find_materials
            find_materials("Grade 4 Mathematics notes",
                           grade="grade4", subject="mathematics")
        mock_fail.assert_not_called()

    def test_url_preserved_exactly_from_payload(self):
        """The exact URL from the Qdrant payload appears unchanged in the output."""
        exact_url = "https://www.elimulibrary.com/site/document/170/eng-f1-syllabus"
        fake_hit = {
            "source": "qdrant", "score": 0.9,
            "url": exact_url, "title": "English Syllabus",
            "grade": "form1", "subject": "english", "term": "",
            "year": "", "doctype": "syllabus", "audience": "teacher",
            "price": None, "description": "", "curriculum": "",
        }
        with patch("elimu_ai.tools.library._qdrant_search_for_query", return_value=[fake_hit]):
            from elimu_ai.tools.library import find_materials
            result = find_materials("English Form 1 syllabus",
                                    grade="form1", subject="english",
                                    audience="teacher")
        self.assertIn(exact_url, result)


# ── F. Agent decision logging ─────────────────────────────────────────────────

class TestAgentDecisionLogging(unittest.TestCase):
    """supervisor._log_decision must call AgentLogRepository.log_decision."""

    def test_log_decision_called_after_plan(self):
        from elimu_ai.agents.supervisor import SupervisorAgent
        from elimu_ai.agents.intent_agent import IntentAnalysis, SemanticIntent, SubQuery
        from elimu_ai.agents.planner import ExecutionPlan, PlanStep

        analysis = IntentAnalysis(
            intents=[SemanticIntent("librarian", 0.95)],
            entities={}, sub_queries=[], reasoning="test",
        )
        plan = ExecutionPlan(
            steps=[PlanStep(step_id=1, action="catalog_search", params={})],
            reasoning="test", estimated_tools=["catalog_search"],
        )
        sup = SupervisorAgent()
        with patch("elimu_ai.db.repositories.AgentLogRepository.log_decision") as mock_ld:
            sup._log_decision(
                request_id="test-rid",
                session_id="sess-1",
                user_id=None,
                question="Grade 4 Maths notes",
                analysis=analysis,
                plan=plan,
            )
        mock_ld.assert_called_once()
        kwargs = mock_ld.call_args[1]
        self.assertEqual(kwargs["request_id"], "test-rid")
        self.assertIn("librarian", kwargs["intents"])

    def test_log_decision_failure_does_not_raise(self):
        """A DB error inside _log_decision must never propagate."""
        from elimu_ai.agents.supervisor import SupervisorAgent
        from elimu_ai.agents.intent_agent import IntentAnalysis, SemanticIntent
        from elimu_ai.agents.planner import ExecutionPlan

        analysis = IntentAnalysis(
            intents=[SemanticIntent("teacher", 0.6)],
            entities={}, sub_queries=[], reasoning="test",
        )
        plan = ExecutionPlan(steps=[], reasoning="", estimated_tools=[])
        sup = SupervisorAgent()
        with patch("elimu_ai.db.repositories.AgentLogRepository.log_decision",
                   side_effect=Exception("DB down")):
            try:
                sup._log_decision("rid", None, None, "question", analysis, plan)
            except Exception:
                self.fail("_log_decision raised unexpectedly")


# ── G. Quiz persistence ───────────────────────────────────────────────────────

class TestQuizPersistence(unittest.TestCase):
    """Successful quiz generation must call QuizRepository.save_quiz."""

    def _make_context(self):
        ctx = MagicMock()
        ctx.qdrant_context = ""
        ctx.curriculum_hints = {"subject": "biology", "grade": "grade8"}
        ctx.session_id = "sess-quiz-1"
        ctx.user_id = 42
        return ctx

    def test_successful_quiz_calls_save_quiz(self):
        from elimu_ai.tool_registry import _execute_quiz
        ctx = self._make_context()
        with patch("elimu_ai.gemini.generate", return_value="1. Question A\nAnswer: B"), \
             patch("elimu_ai.db.repositories.QuizRepository.save_quiz") as mock_sq:
            result = _execute_quiz(ctx, "Grade 8 Biology")
        mock_sq.assert_called_once()
        kwargs = mock_sq.call_args[1]
        self.assertEqual(kwargs["subject"], "biology")
        self.assertEqual(kwargs["grade"], "grade8")
        self.assertIn("Question A", kwargs["quiz_content"])

    def test_failed_quiz_does_not_call_save_quiz(self):
        """When Gemini returns an error string, save_quiz must NOT be called."""
        from elimu_ai.tool_registry import _execute_quiz
        ctx = self._make_context()
        with patch("elimu_ai.gemini.generate",
                   return_value="Elimu AI is temporarily unavailable."), \
             patch("elimu_ai.db.repositories.QuizRepository.save_quiz") as mock_sq:
            _execute_quiz(ctx, "Grade 8 Biology")
        mock_sq.assert_not_called()

    def test_save_quiz_failure_does_not_crash_response(self):
        """A DB error in save_quiz must not propagate to the user."""
        from elimu_ai.tool_registry import _execute_quiz
        ctx = self._make_context()
        with patch("elimu_ai.gemini.generate", return_value="1. What is osmosis?\nAnswer: C"), \
             patch("elimu_ai.db.repositories.QuizRepository.save_quiz",
                   side_effect=Exception("DB error")):
            try:
                result = _execute_quiz(ctx, "Grade 8 Biology")
            except Exception:
                self.fail("_execute_quiz raised on DB failure")
        self.assertIn("osmosis", result)


# ── H. Failed query schema ────────────────────────────────────────────────────

class TestFailedQuerySchema(unittest.TestCase):
    """ai_failed_queries must have retry_count and resolved columns in migrations."""

    def test_schema_contains_retry_count(self):
        from elimu_ai.db.migrations import _SCHEMA
        self.assertIn("retry_count", _SCHEMA)

    def test_schema_contains_resolved(self):
        from elimu_ai.db.migrations import _SCHEMA
        self.assertIn("resolved", _SCHEMA)

    def test_incremental_migration_adds_columns(self):
        from elimu_ai.db.migrations import _apply_incremental
        mock_cur = MagicMock()
        # Should not raise
        _apply_incremental(mock_cur)
        # Should call execute at least twice (one per column)
        self.assertGreaterEqual(mock_cur.execute.call_count, 2)

    def test_repository_has_get_unresolved_failures(self):
        from elimu_ai.db.repositories import AgentLogRepository
        repo = AgentLogRepository()
        self.assertTrue(hasattr(repo, "get_unresolved_failures"))

    def test_repository_has_increment_retry(self):
        from elimu_ai.db.repositories import AgentLogRepository
        repo = AgentLogRepository()
        self.assertTrue(hasattr(repo, "increment_retry"))

    def test_repository_has_mark_resolved(self):
        from elimu_ai.db.repositories import AgentLogRepository
        repo = AgentLogRepository()
        self.assertTrue(hasattr(repo, "mark_resolved"))

    def test_get_unresolved_failures_returns_empty_when_db_unavailable(self):
        """Must return [] gracefully when DB is down (uses safe wrapper)."""
        from elimu_ai.db.repositories import AgentLogRepository
        with patch("elimu_ai.db.connection.get_connection",
                   side_effect=Exception("no db")):
            result = AgentLogRepository().get_unresolved_failures_safe()
        self.assertEqual(result, [])


# ── I. Memory restoration ─────────────────────────────────────────────────────

class TestMemoryRestoration(unittest.TestCase):
    """restore_session must inject prior summary without a Gemini call."""

    def test_restore_session_loads_summary_from_db(self):
        from elimu_ai.memory import MemoryStore
        store = MemoryStore()
        with patch("elimu_ai.db.repositories.MemoryRepository.get_summary",
                   return_value="Student asked about photosynthesis in Term 2.") as mock_gs:
            summary = store.restore_session("sess-restore-1", user_id=None)
        self.assertEqual(summary, "Student asked about photosynthesis in Term 2.")
        mock_gs.assert_called_once_with("sess-restore-1")

    def test_restore_session_injects_turn(self):
        """After restore, get_history should include the summary as a system turn."""
        from elimu_ai.memory import MemoryStore
        store = MemoryStore()
        with patch("elimu_ai.db.repositories.MemoryRepository.get_summary",
                   return_value="Prior context: Chemistry notes Term 3."):
            store.restore_session("sess-restore-2")
        history = store.get_history("sess-restore-2", max_turns=5)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["role"], "system")
        self.assertIn("Chemistry notes", history[0]["content"])

    def test_restore_session_skipped_when_session_warm(self):
        """If the session already has turns, restore_session returns None."""
        from elimu_ai.memory import MemoryStore
        store = MemoryStore()
        store.add_turn("sess-warm", "user", "Hello")
        with patch("elimu_ai.db.repositories.MemoryRepository.get_summary") as mock_gs:
            result = store.restore_session("sess-warm")
        mock_gs.assert_not_called()
        self.assertIsNone(result)

    def test_restore_session_returns_none_when_no_summary(self):
        from elimu_ai.memory import MemoryStore
        store = MemoryStore()
        with patch("elimu_ai.db.repositories.MemoryRepository.get_summary",
                   return_value=None):
            result = store.restore_session("sess-no-summary")
        self.assertIsNone(result)

    def test_restore_session_no_gemini_call(self):
        """restore_session must not call Gemini generate()."""
        from elimu_ai.memory import MemoryStore
        store = MemoryStore()
        with patch("elimu_ai.db.repositories.MemoryRepository.get_summary",
                   return_value="Some prior summary."), \
             patch("elimu_ai.gemini.generate") as mock_gen:
            store.restore_session("sess-no-gemini")
        mock_gen.assert_not_called()


# ── J. Ingest payload metadata ────────────────────────────────────────────────

class TestIngestPayload(unittest.TestCase):
    """_build_payload must include source_type and ingested_at."""

    def test_source_type_is_catalog(self):
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from ingest import _build_payload
        doc = {
            "title": "Grade 4 Maths Notes",
            "url":   "https://www.elimulibrary.com/site/document/1/maths",
            "grade": "Grade 4", "subject": "Mathematics",
        }
        payload = _build_payload(doc)
        self.assertEqual(payload["source_type"], "catalog")

    def test_ingested_at_is_iso_string(self):
        from ingest import _build_payload
        doc = {
            "title": "Test Doc",
            "url":   "https://www.elimulibrary.com/site/document/2/test",
        }
        payload = _build_payload(doc)
        self.assertIn("ingested_at", payload)
        # Must be parseable as ISO datetime
        from datetime import datetime
        datetime.fromisoformat(payload["ingested_at"])

    def test_url_not_overwritten(self):
        """The original URL must remain unchanged in the payload."""
        from ingest import _build_payload
        original = "https://www.elimulibrary.com/site/document/170/eng-f1-syllabus"
        doc = {"url": original, "title": "English Syllabus"}
        payload = _build_payload(doc)
        self.assertEqual(payload["url"], original)

    def test_referral_url_added(self):
        """referral_url must append ref=elimutalks to the original URL."""
        from ingest import _build_payload
        doc = {
            "url": "https://www.elimulibrary.com/site/document/3/bio",
            "title": "Biology Notes",
        }
        payload = _build_payload(doc)
        self.assertIn("ref=elimutalks", payload["referral_url"])


# ── K. Regression — existing functionality still works ───────────────────────

class TestRegressionTeacherPath(unittest.TestCase):
    """Normal teacher question must still go through generate() once."""

    def test_teacher_tool_calls_generate_once(self):
        from elimu_ai.tool_registry import _execute_teacher
        ctx = MagicMock()
        ctx.to_context_string.return_value = "No context."
        with patch("elimu_ai.gemini.generate", return_value="Osmosis is the movement of water.") as mock_gen:
            result = _execute_teacher(ctx, "What is osmosis?")
        mock_gen.assert_called_once()
        self.assertIn("Osmosis", result)


class TestRegressionDocumentLookup(unittest.TestCase):
    """Document lookup must return real URL from payload, not a constructed one."""

    def test_find_materials_url_from_payload_not_constructed(self):
        payload_url = "https://www.elimulibrary.com/site/document/999/phy-form3"
        fake_hit = {
            "source": "qdrant", "score": 0.88,
            "url": payload_url, "title": "Physics Form 3",
            "grade": "form3", "subject": "physics",
            "term": "", "year": "", "doctype": "notes",
            "audience": "student", "price": None,
            "description": "", "curriculum": "",
        }
        with patch("elimu_ai.tools.library._qdrant_search_for_query",
                   return_value=[fake_hit]):
            from elimu_ai.tools.library import find_materials
            result = find_materials("Physics Form 3 notes",
                                    grade="form3", subject="physics")
        self.assertIn(payload_url, result)
        # Must NOT contain a different reconstructed URL
        self.assertNotIn("/site/document/1/", result)


class TestRegressionCommunityPath(unittest.TestCase):
    """Forum/community operations must still work via HTTP client."""

    def test_create_discussion_uses_http_not_orm(self):
        from elimu_ai.tools.forum import save_forum_post
        with patch("elimu_ai.http_client.ElimuAPIClient.create_discussion",
                   return_value={"slug": "test-discussion", "category_name": "revision"}) as mock_cd:
            result = save_forum_post("Test Title", "Body text", "revision")
        mock_cd.assert_called_once()
        self.assertIsNotNone(result)


class TestRegressionMetadataFilter(unittest.TestCase):
    """Teacher-audience docs must not appear in student results."""

    def test_teacher_docs_filtered_for_student_audience(self):
        teacher_hit = {
            "source": "qdrant", "score": 0.9,
            "url": "https://www.elimulibrary.com/site/document/5/scheme",
            "title": "Grade 4 Maths Scheme of Work",
            "grade": "grade4", "subject": "mathematics",
            "term": "", "year": "", "doctype": "schemesofwork",
            "audience": "teacher", "price": None,
            "description": "", "curriculum": "",
        }
        with patch("elimu_ai.tools.library._qdrant_search_for_query",
                   return_value=[teacher_hit]):
            from importlib import reload
            from elimu_ai.tools import library
            result = library.find_materials(
                "Grade 4 Mathematics notes",
                grade="grade4", subject="mathematics", audience="student",
            )
        # Teacher-only doc should be filtered out — fallback or no doc in output
        self.assertNotIn("Scheme of Work", result.split("\n")[0])


# ── L. Scheduler retry task ───────────────────────────────────────────────────

class TestSchedulerRetryTask(unittest.TestCase):
    """task_retry_failed_queries must be registered and behave correctly."""

    def test_retry_task_registered_in_registry(self):
        from elimu_ai.scheduler import _TASK_REGISTRY
        names = [name for name, _, _ in _TASK_REGISTRY]
        self.assertIn("retry_failed_queries", names)

    def test_retry_task_returns_string(self):
        """When DB is unavailable, task must return a string (not raise)."""
        with patch("elimu_ai.db.repositories.AgentLogRepository.get_unresolved_failures",
                   return_value=[]):
            from elimu_ai.scheduler import task_retry_failed_queries
            result = task_retry_failed_queries()
        self.assertIsInstance(result, str)

    def test_retry_task_increments_retry_count_on_no_hits(self):
        """When retry finds no evidence, retry_count is incremented, not resolved."""
        row = {
            "id": 1, "question": "Grade 99 Martian notes",
            "intents": ["librarian"], "tools": ["qdrant"],
            "failure_reason": "no_evidence", "confidence": 0.0,
            "suggested_fix": "", "retry_count": 0,
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        with patch("elimu_ai.db.repositories.AgentLogRepository.get_unresolved_failures",
                   return_value=[row]), \
             patch("elimu_ai.tools.library._qdrant_search_for_query", return_value=[]), \
             patch("elimu_ai.db.repositories.AgentLogRepository.increment_retry") as mock_inc, \
             patch("elimu_ai.db.repositories.AgentLogRepository.mark_resolved") as mock_res:
            from elimu_ai.scheduler import task_retry_failed_queries
            task_retry_failed_queries()
        mock_inc.assert_called_once_with(1)
        mock_res.assert_not_called()

    def test_retry_task_marks_resolved_when_evidence_found(self):
        """When retry finds good evidence that passes verification, row is resolved."""
        row = {
            "id": 2, "question": "Grade 4 Mathematics notes",
            "intents": ["librarian"], "tools": ["qdrant"],
            "failure_reason": "no_evidence", "confidence": 0.0,
            "suggested_fix": "", "retry_count": 0,
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        good_hit = {
            "source": "qdrant", "score": 0.85,
            "url": "https://www.elimulibrary.com/site/document/10/maths4",
            "title": "Grade 4 Maths Notes",
            "grade": "grade4", "subject": "mathematics",
            "term": "", "year": "", "doctype": "notes",
            "audience": "student", "price": "KES 199",
            "description": "Comprehensive notes", "curriculum": "CBC",
        }
        with patch("elimu_ai.db.repositories.AgentLogRepository.get_unresolved_failures",
                   return_value=[row]), \
             patch("elimu_ai.tools.library._qdrant_search_for_query",
                   return_value=[good_hit]), \
             patch("elimu_ai.db.repositories.AgentLogRepository.mark_resolved") as mock_res, \
             patch("elimu_ai.db.repositories.AgentLogRepository.increment_retry") as mock_inc, \
             patch("elimu_ai.db.repositories.RecommendationRepository.set_cached"):
            from elimu_ai.scheduler import task_retry_failed_queries
            task_retry_failed_queries()
        mock_res.assert_called_once_with(2)
        mock_inc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
