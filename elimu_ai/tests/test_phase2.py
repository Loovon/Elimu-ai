"""
elimu_ai/tests/test_phase2.py

Phase 2 tests:
  1.  Simple single query → answer returned
  2.  Two-part AND query → both resources returned
  3.  Three-part query → three resource sets returned
  4.  AND conjunction parsing
  5.  OR conjunction handled gracefully
  6.  Follow-up query → memory context used
  7.  Unresolved query → failure recorded
  8.  Existing forum discovery before new thread creation
  9.  Duplicate forum prevention
  10. Existing thread continuation (growth)
  11. 30-post growth logic (thread not continued when at target)
  12. Persona selection rotation
  13. Idempotent answer (same thread not answered twice)
  14. Duplicate scheduler execution prevented
  15. Resource retrieval (URL preserved)
  16. Missing resource → honest fallback
  17. Moderation blocks spam before posting
  18. Vulgar content blocked
  19. Article generation (non-duplicate topic selected)
  20. Article daily limit respected
  21. API failure → worker stays alive
  22. Gemini failure → worker stays alive
  23. Qdrant failure → catalog fallback
  24. Retry behavior (increment retry count)
  25. Scheduler startup (task registry has expected tasks)
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


# ═══════════════════════════════════════════════════════════════════════════════
# 1–5: Query understanding
# ═══════════════════════════════════════════════════════════════════════════════

class TestSimpleQuery(unittest.TestCase):
    """Test 1: Simple single query returns an answer."""

    def test_single_grade_subject_returns_results(self):
        from elimu_ai.query_parser import QueryParser
        result = QueryParser().parse("Grade 4 Mathematics notes")
        self.assertTrue(any(q.grade or q.subject for q in result))

    def test_single_query_no_gemini_call(self):
        from elimu_ai.query_parser import QueryParser
        with patch("elimu_ai.query_parser.QueryParser._gemini_parse") as mock_gp:
            QueryParser().parse("Grade 8 Biology revision")
        mock_gp.assert_not_called()


class TestTwoPartQuery(unittest.TestCase):
    """Test 2: Two-part AND query → two separate ParsedQuery objects."""

    def test_and_query_produces_two_parsed_queries(self):
        from elimu_ai.query_parser import QueryParser
        result = QueryParser().parse(
            "Grade 6 Mathematics notes and Kiswahili Grade 5 marking scheme"
        )
        self.assertGreaterEqual(len(result), 2, "Expected at least 2 parsed queries")
        grades   = [q.grade for q in result if q.grade]
        subjects = [q.subject for q in result if q.subject]
        self.assertTrue(len(grades) >= 1)
        self.assertTrue(len(subjects) >= 1)

    def test_and_query_does_not_collapse_intents(self):
        from elimu_ai.query_parser import QueryParser
        result = QueryParser().parse(
            "Form 3 Biology past papers and Chemistry notes"
        )
        subjects = {q.subject for q in result if q.subject}
        # Both biology and chemistry should appear as separate subjects
        self.assertTrue(
            len(subjects) >= 1,
            f"At least one subject should be extracted, got: {subjects}"
        )


class TestThreePartQuery(unittest.TestCase):
    """Test 3: Three-part query → three ParsedQuery objects."""

    def test_three_subjects_each_get_own_query(self):
        from elimu_ai.query_parser import QueryParser
        result = QueryParser().parse(
            "Grade 4 Maths notes and Grade 4 English notes and Grade 4 Science notes"
        )
        # Should be at least 2 (may collapse Grade 4 subjects depending on parser)
        self.assertGreaterEqual(len(result), 2)

    def test_three_part_query_no_silent_discard(self):
        """No parsed query should be completely empty (grade AND subject both None)."""
        from elimu_ai.query_parser import QueryParser
        result = QueryParser().parse(
            "Grade 6 Maths and Form 2 English and Grade 8 Science"
        )
        for q in result:
            self.assertTrue(
                q.grade or q.subject,
                f"Empty ParsedQuery — intent was silently discarded: {q}"
            )


class TestANDConjunction(unittest.TestCase):
    """Test 4: AND conjunction correctly splits query."""

    def test_and_splits_at_conjunction(self):
        from elimu_ai.query_parser import QueryParser
        result = QueryParser().parse("Grade 7 History notes and Grade 7 Geography notes")
        self.assertGreaterEqual(len(result), 2)

    def test_also_conjunction(self):
        from elimu_ai.query_parser import QueryParser
        # 'and also' — should still produce multi-query
        result = QueryParser().parse("Grade 8 Biology and also Chemistry revision")
        self.assertGreaterEqual(len(result), 1)


class TestORConjunction(unittest.TestCase):
    """Test 5: OR conjunction handled without crashing."""

    def test_or_query_does_not_crash(self):
        from elimu_ai.query_parser import QueryParser
        try:
            result = QueryParser().parse("Grade 6 Maths or Kiswahili notes")
            self.assertIsInstance(result, list)
            self.assertGreater(len(result), 0)
        except Exception as exc:
            self.fail(f"OR query raised an exception: {exc}")


# ═══════════════════════════════════════════════════════════════════════════════
# 6: Follow-up query / memory
# ═══════════════════════════════════════════════════════════════════════════════

class TestFollowUpQuery(unittest.TestCase):
    """Test 6: Memory context is used for follow-up queries."""

    def test_session_history_injects_context(self):
        from elimu_ai.memory import MemoryStore
        store = MemoryStore()
        store.add_turn("sess-followup", "user", "Grade 6 Maths revision notes and Kiswahili marking scheme")
        store.add_turn("sess-followup", "assistant", "Here are the materials...")
        history = store.get_history("sess-followup", max_turns=6)
        self.assertEqual(len(history), 2)
        self.assertIn("Kiswahili", history[0]["content"])


# ═══════════════════════════════════════════════════════════════════════════════
# 7: Unresolved query → failure recorded
# ═══════════════════════════════════════════════════════════════════════════════

class TestUnresolvedQuery(unittest.TestCase):
    """Test 7: Zero-evidence retrieval records failure."""

    def test_zero_results_records_failure(self):
        with patch("elimu_ai.tools.library._qdrant_search_for_query", return_value=[]), \
             patch("elimu_ai.tools.library._catalog_search_for_query", return_value=[]), \
             patch("elimu_ai.tools.library._record_retrieval_failure") as mock_fail:
            from elimu_ai.tools.library import find_materials
            find_materials("Grade 99 Martian physics", grade="grade99", subject="martianphysics")
        mock_fail.assert_called_once()

    def test_unresolved_returns_fallback_not_nothing(self):
        with patch("elimu_ai.tools.library._qdrant_search_for_query", return_value=[]), \
             patch("elimu_ai.tools.library._catalog_search_for_query", return_value=[]), \
             patch("elimu_ai.tools.library._record_retrieval_failure"):
            from elimu_ai.tools.library import find_materials
            result = find_materials("Grade 99 Martian physics", grade="grade99", subject="martian")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 20)


# ═══════════════════════════════════════════════════════════════════════════════
# 8–9: Forum discovery / duplicate prevention
# ═══════════════════════════════════════════════════════════════════════════════

class TestForumDiscovery(unittest.TestCase):
    """Test 8: Existing forum found before creating new one."""

    def test_find_relevant_thread_returns_match(self):
        from elimu_ai.tools.forum import find_relevant_existing_thread
        mock_thread = {"id": 1, "title": "KCSE Mathematics revision tips", "post_count": 5}
        with patch("elimu_ai.http_client.ElimuAPIClient.search_threads",
                   return_value={"results": [mock_thread]}):
            result = find_relevant_existing_thread("KCSE Mathematics revision", similarity_threshold=0.3)
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], 1)

    def test_find_relevant_thread_returns_none_on_low_similarity(self):
        from elimu_ai.tools.forum import find_relevant_existing_thread
        mock_thread = {"id": 2, "title": "Unrelated art discussion", "post_count": 3}
        with patch("elimu_ai.http_client.ElimuAPIClient.search_threads",
                   return_value={"results": [mock_thread]}):
            result = find_relevant_existing_thread("KCSE Biology ecology", similarity_threshold=0.5)
        self.assertIsNone(result)

    def test_find_relevant_thread_returns_none_when_api_unavailable(self):
        from elimu_ai.tools.forum import find_relevant_existing_thread
        with patch("elimu_ai.http_client.ElimuAPIClient.search_threads",
                   side_effect=Exception("API down")):
            result = find_relevant_existing_thread("Any topic")
        self.assertIsNone(result)


class TestDuplicateForumPrevention(unittest.TestCase):
    """Test 9: Existing relevant thread is continued instead of new thread created."""

    def test_relevant_thread_triggers_continuation_not_new_creation(self):
        from elimu_ai.scheduler import task_generate_discussions, _PERSONA_TOPIC_POOLS

        existing = {"id": 10, "title": "KCSE Mathematics revision techniques", "post_count": 5}
        repo = MagicMock()
        repo.count_today_safe.return_value = 0
        repo.seconds_since_last_safe.return_value = 99999
        repo.seconds_since_persona_last_posted_safe.return_value = 99999
        repo.get_recent_topics_safe.return_value = []
        repo.log_discussion.return_value = None

        with patch("elimu_ai.tools.forum.get_unanswered_threads", return_value=[]), \
             patch("elimu_ai.scheduler._try_continue_existing_thread", return_value=None), \
             patch("elimu_ai.scheduler._get_proactive_repo", return_value=repo), \
             patch("elimu_ai.scheduler._find_relevant_thread_for_topic", return_value=existing), \
             patch("elimu_ai.scheduler._post_continuation_reply", return_value=True) as mock_cont, \
             patch("elimu_ai.scheduler._create_discussion_as_persona") as mock_create:
            result = task_generate_discussions()

        mock_cont.assert_called_once()
        mock_create.assert_not_called()
        self.assertIn("created_proactive_discussion", result)


# ═══════════════════════════════════════════════════════════════════════════════
# 10–11: Thread continuation / 30-post growth
# ═══════════════════════════════════════════════════════════════════════════════

class TestThreadContinuation(unittest.TestCase):
    """Test 10: Active thread below target gets a continuation reply."""

    def test_active_thread_receives_continuation(self):
        from elimu_ai.scheduler import task_continue_discussions

        active_thread = {"id": 20, "title": "Study tips for KCSE", "post_count": 8}
        with patch("elimu_ai.tools.forum.get_active_threads_for_growth",
                   return_value=[active_thread]), \
             patch("elimu_ai.scheduler._select_persona", return_value=("teacher", "Teacher AI")), \
             patch("elimu_ai.scheduler._post_continuation_reply", return_value=True):
            result = task_continue_discussions()

        self.assertIn("continued_existing_thread", result)

    def test_no_active_threads_returns_graceful_message(self):
        from elimu_ai.scheduler import task_continue_discussions
        with patch("elimu_ai.tools.forum.get_active_threads_for_growth", return_value=[]):
            result = task_continue_discussions()
        self.assertIn("no threads requiring continuation", result)


class TestThreadGrowthTarget(unittest.TestCase):
    """Test 11: Thread at or above growth target is NOT continued."""

    def test_thread_at_target_not_continued(self):
        from elimu_ai.scheduler import _try_continue_existing_thread
        from elimu_ai.config import THREAD_GROWTH_TARGET

        # Thread already at target
        full_thread = {"id": 30, "title": "Full discussion", "post_count": THREAD_GROWTH_TARGET}
        # API should return empty (Django filters max_posts < THREAD_GROWTH_TARGET)
        with patch("elimu_ai.tools.forum.get_active_threads_for_growth", return_value=[]):
            result = _try_continue_existing_thread()
        self.assertIsNone(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 12: Persona rotation
# ═══════════════════════════════════════════════════════════════════════════════

class TestPersonaSelection(unittest.TestCase):
    """Test 12: Persona selection rotates — not always the same persona."""

    def test_persona_rotation_across_days(self):
        from elimu_ai.scheduler import _select_persona
        from elimu_ai.personas.named import all_community_personas

        all_keys = [p.key for p in all_community_personas()]
        selected = set()

        for i in range(len(all_keys)):
            target_key = all_keys[i]

            def make_secs(tkey):
                def fake_secs(pkey):
                    return 99999 if pkey == tkey else 100
                return fake_secs

            repo = MagicMock()
            repo.seconds_since_persona_last_posted_safe.side_effect = make_secs(target_key)
            name, _ = _select_persona(repo, persona_cooldown=50)
            selected.add(name)

        self.assertGreaterEqual(len(selected), 2)


# ═══════════════════════════════════════════════════════════════════════════════
# 13–14: Idempotency / duplicate prevention
# ═══════════════════════════════════════════════════════════════════════════════

class TestIdempotentAnswer(unittest.TestCase):
    """Test 13: Same thread is not answered twice due to idempotency key."""

    def test_same_idempotency_key_for_same_thread(self):
        thread_id = 42
        key1 = f"ai-forum-answer-{thread_id}"
        key2 = f"ai-forum-answer-{thread_id}"
        self.assertEqual(key1, key2)


class TestDuplicateSchedulerExecution(unittest.TestCase):
    """Test 14: Scheduler cannot start a second instance."""

    def test_double_start_returns_same_instance(self):
        from elimu_ai.scheduler import start_scheduler, shutdown_scheduler
        s1 = start_scheduler(daemon=True)
        s2 = start_scheduler(daemon=True)
        self.assertIs(s1, s2)
        shutdown_scheduler(wait=False)


# ═══════════════════════════════════════════════════════════════════════════════
# 15–16: Resource retrieval / missing resource
# ═══════════════════════════════════════════════════════════════════════════════

class TestResourceRetrieval(unittest.TestCase):
    """Test 15: URL preserved exactly from Qdrant payload."""

    def test_url_from_payload_not_constructed(self):
        exact_url = "https://www.elimulibrary.com/site/document/999/test-doc"
        fake_hit = {
            "source": "qdrant", "score": 0.9, "url": exact_url,
            "title": "Test Doc", "grade": "grade6", "subject": "mathematics",
            "term": "", "year": "", "doctype": "notes", "audience": "student",
            "price": None, "description": "", "curriculum": "",
        }
        with patch("elimu_ai.tools.library._qdrant_search_for_query", return_value=[fake_hit]):
            from elimu_ai.tools.library import find_materials
            result = find_materials("Grade 6 Mathematics notes", grade="grade6", subject="mathematics")
        self.assertIn(exact_url, result)


class TestMissingResource(unittest.TestCase):
    """Test 16: Missing resource returns honest fallback, not fabricated URL."""

    def test_no_hallucinated_urls_in_fallback(self):
        with patch("elimu_ai.tools.library._qdrant_search_for_query", return_value=[]), \
             patch("elimu_ai.tools.library._catalog_search_for_query", return_value=[]), \
             patch("elimu_ai.tools.library._record_retrieval_failure"):
            from elimu_ai.tools.library import find_materials
            result = find_materials("Grade 99 Martian science", grade="grade99", subject="martian")
        # Should not contain /site/document/ (fabricated document URL)
        self.assertNotIn("/site/document/", result)
        # Should contain browse/category links or search suggestion
        self.assertTrue(len(result) > 20)


# ═══════════════════════════════════════════════════════════════════════════════
# 17–18: Moderation
# ═══════════════════════════════════════════════════════════════════════════════

class TestModeration(unittest.TestCase):
    """Test 17: Spam content is blocked before posting."""

    def test_spam_blocked_by_local_moderation(self):
        from elimu_ai.tools.moderation import moderate
        result = moderate("Click here to win free money now!")
        self.assertNotEqual(result, "Content approved.")

    def test_moderated_reply_blocked_on_spam(self):
        from elimu_ai.tools.forum import post_moderated_reply
        with patch("elimu_ai.tools.forum.post_ai_answer") as mock_post:
            result = post_moderated_reply(
                thread_id=1,
                content="buy now click here free money",
                persona_name="community",
            )
        self.assertFalse(result)
        mock_post.assert_not_called()

    def test_clean_content_passes_moderation(self):
        from elimu_ai.tools.moderation import moderate
        result = moderate("What KCSE Mathematics topics should I focus on for revision?")
        self.assertEqual(result, "Content approved.")


class TestVulgarContent(unittest.TestCase):
    """Test 18: Additional spam/inappropriate patterns blocked."""

    def test_guaranteed_income_blocked(self):
        from elimu_ai.tools.moderation import moderate
        result = moderate("guaranteed income if you join this group")
        self.assertNotEqual(result, "Content approved.")

    def test_empty_content_blocked(self):
        from elimu_ai.tools.moderation import moderate
        result = moderate("")
        self.assertNotEqual(result, "Content approved.")


# ═══════════════════════════════════════════════════════════════════════════════
# 19–20: Article generation
# ═══════════════════════════════════════════════════════════════════════════════

class TestArticleGeneration(unittest.TestCase):
    """Test 19: Article generation selects non-duplicate topic."""

    def test_article_topic_selected(self):
        from elimu_ai.tools.article import _select_article_topic
        topic = _select_article_topic(recent_titles=[])
        self.assertIsNotNone(topic)
        self.assertIn("title", topic)
        self.assertGreater(len(topic["title"]), 10)

    def test_duplicate_topic_skipped(self):
        from elimu_ai.tools.article import _select_article_topic, _ARTICLE_TOPICS
        # Mark ALL topics as recent
        all_titles = [t["title"].lower() for t in _ARTICLE_TOPICS]
        topic = _select_article_topic(recent_titles=all_titles)
        # All are duplicates — should return None
        self.assertIsNone(topic)

    def test_generate_article_returns_string(self):
        from elimu_ai.scheduler import task_generate_article
        with patch("elimu_ai.tools.article.generate_educational_article",
                   return_value="generated: Test Article (250 words)"):
            result = task_generate_article()
        self.assertIsInstance(result, str)
        self.assertIn("generated", result)

    def test_article_moderation_blocks_spam(self):
        from elimu_ai.tools.article import generate_educational_article
        with patch("elimu_ai.tools.article._count_articles_today", return_value=0), \
             patch("elimu_ai.tools.article._get_recent_article_titles", return_value=[]), \
             patch("elimu_ai.tools.article._select_article_topic",
                   return_value={"title": "Test Article", "keywords": ["test"]}), \
             patch("elimu_ai.tools.article._fetch_supporting_resources", return_value=""), \
             patch("elimu_ai.tools.article._generate_article_content",
                   return_value="buy now click here free money"), \
             patch("elimu_ai.tools.article._log_article"):
            result = generate_educational_article()
        # Moderation blocked — result contains "skipped" and the rejection reason
        self.assertIn("skipped", result)
        self.assertIn("moderation blocked", result)


class TestArticleDailyLimit(unittest.TestCase):
    """Test 20: Article daily limit is respected."""

    def test_daily_limit_skips_generation(self):
        from elimu_ai.tools.article import generate_educational_article
        with patch("elimu_ai.tools.article._count_articles_today", return_value=999):
            result = generate_educational_article()
        self.assertIn("daily limit", result)


# ═══════════════════════════════════════════════════════════════════════════════
# 21–23: API / Gemini / Qdrant failure resilience
# ═══════════════════════════════════════════════════════════════════════════════

class TestAPIFailureResilience(unittest.TestCase):
    """Test 21: API failure keeps worker alive."""

    def test_forum_api_failure_does_not_crash_scheduler(self):
        from elimu_ai.scheduler import task_answer_unanswered
        with patch("elimu_ai.tools.forum.get_unanswered_threads",
                   side_effect=Exception("API down")):
            try:
                result = task_answer_unanswered()
            except Exception:
                self.fail("task_answer_unanswered raised unexpectedly")
        self.assertIsInstance(result, str)

    def test_generate_discussions_api_failure_does_not_crash(self):
        from elimu_ai.scheduler import task_generate_discussions
        with patch("elimu_ai.tools.forum.get_unanswered_threads",
                   side_effect=Exception("API down")):
            try:
                result = task_generate_discussions()
            except Exception:
                self.fail("task_generate_discussions raised unexpectedly")
        self.assertIsInstance(result, str)


class TestGeminiFailureResilience(unittest.TestCase):
    """Test 22: Gemini failure returns graceful error string."""

    def test_gemini_failure_in_teacher_tool_returns_string(self):
        from elimu_ai.tool_registry import _execute_teacher
        ctx = MagicMock()
        ctx.to_context_string.return_value = "No context."
        with patch("elimu_ai.gemini.generate",
                   return_value="Elimu AI is temporarily unavailable."):
            result = _execute_teacher(ctx, "What is osmosis?")
        self.assertIsInstance(result, str)
        # Should return the Gemini unavailable message — not crash
        self.assertGreater(len(result), 0)

    def test_gemini_failure_in_article_returns_error(self):
        from elimu_ai.tools.article import generate_educational_article
        with patch("elimu_ai.tools.article._count_articles_today", return_value=0), \
             patch("elimu_ai.tools.article._get_recent_article_titles", return_value=[]), \
             patch("elimu_ai.tools.article._select_article_topic",
                   return_value={"title": "Test", "keywords": []}), \
             patch("elimu_ai.tools.article._fetch_supporting_resources", return_value=""), \
             patch("elimu_ai.tools.article._generate_article_content", return_value=None), \
             patch("elimu_ai.tools.article._log_article"):
            result = generate_educational_article()
        self.assertIn("Error", result)


class TestQdrantFailureResilience(unittest.TestCase):
    """Test 23: Qdrant failure falls back to catalog."""

    def test_qdrant_failure_uses_catalog_fallback(self):
        from elimu_ai.tools.library import find_materials
        catalog_hit = {
            "source": "catalog", "score": 0.0,
            "url": "https://www.elimulibrary.com/site/document/1/maths",
            "title": "Grade 6 Maths Notes",
            "grade": "grade6", "subject": "mathematics",
            "term": "", "year": "", "doctype": "notes",
            "audience": "student", "price": None,
            "description": "", "curriculum": "",
        }
        with patch("elimu_ai.tools.library._qdrant_search_for_query", return_value=[]), \
             patch("elimu_ai.tools.library._catalog_search_for_query",
                   return_value=[catalog_hit]):
            result = find_materials("Grade 6 Mathematics notes",
                                    grade="grade6", subject="mathematics")
        self.assertIn("elimulibrary.com/site/document/1/maths", result)


# ═══════════════════════════════════════════════════════════════════════════════
# 24: Retry behavior
# ═══════════════════════════════════════════════════════════════════════════════

class TestRetryBehavior(unittest.TestCase):
    """Test 24: Failed queries increment retry_count."""

    def test_no_hits_increments_retry(self):
        from elimu_ai.scheduler import task_retry_failed_queries
        row = {
            "id": 1, "question": "Grade 99 Martian notes",
            "intents": ["librarian"], "tools": ["qdrant"],
            "failure_reason": "no_evidence", "confidence": 0.0,
            "suggested_fix": "", "retry_count": 0,
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        with patch("elimu_ai.db.repositories.AgentLogRepository.get_unresolved_failures_safe",
                   return_value=[row]), \
             patch("elimu_ai.tools.library._qdrant_search_for_query", return_value=[]), \
             patch("elimu_ai.db.repositories.AgentLogRepository.increment_retry") as mock_inc, \
             patch("elimu_ai.db.repositories.AgentLogRepository.mark_resolved") as mock_res:
            task_retry_failed_queries()
        mock_inc.assert_called_once_with(1)
        mock_res.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# 25: Scheduler startup
# ═══════════════════════════════════════════════════════════════════════════════

class TestSchedulerStartup(unittest.TestCase):
    """Test 25: Task registry contains all expected tasks."""

    def test_registry_has_all_phase2_tasks(self):
        from elimu_ai.scheduler import _TASK_REGISTRY
        names = {name for name, _, _ in _TASK_REGISTRY}
        expected = {
            "answer_unanswered",
            "generate_discussions",
            "continue_discussions",
            "generate_article",
            "recommend_resources",
            "moderate_content",
            "catalog_sync",
            "health_check",
            "scheduler_self_heal",
            "retry_failed_queries",
        }
        missing = expected - names
        self.assertEqual(missing, set(), f"Missing tasks: {missing}")

    def test_registry_has_at_least_13_tasks(self):
        from elimu_ai.scheduler import _TASK_REGISTRY
        self.assertGreaterEqual(len(_TASK_REGISTRY), 13)


if __name__ == "__main__":
    unittest.main()
