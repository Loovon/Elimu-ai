"""
elimu_ai/tests/test_continue_discussions.py

Targeted tests for the dual-behavior task_continue_discussions():
  A. Existing 30-post continuation still works
  B. A separate unanswered/low-reply thread can be selected
  C. Both behaviors coexist without one blocking the other
  D. persona_key preserved during continuation replies
  E. persona_key preserved during unanswered-thread replies
  F. HTTP client receives persona_key correctly
  G. Existing idempotency still works
  H. Existing moderation still works
  I. Scheduler task registry not broken
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# A. Existing 30-post continuation still works
# ─────────────────────────────────────────────────────────────────────────────
class TestExistingContinuationPreserved(unittest.TestCase):

    def test_step1_continues_existing_thread(self):
        from elimu_ai.scheduler import task_continue_discussions

        with patch("elimu_ai.scheduler._try_continue_existing_thread",
                   return_value="continued_existing_thread: id=52 posts=11/30 persona=teacher_01") as mock_cont, \
             patch("elimu_ai.scheduler._participate_unanswered_thread",
                   return_value=None):
            result = task_continue_discussions()

        mock_cont.assert_called_once()
        self.assertIn("continued_existing_thread", result)
        self.assertIn("id=52", result)

    def test_step1_result_included_in_output(self):
        from elimu_ai.scheduler import task_continue_discussions

        cont_result = "continued_existing_thread: id=10 posts=5/30 persona=student_02"
        with patch("elimu_ai.scheduler._try_continue_existing_thread",
                   return_value=cont_result), \
             patch("elimu_ai.scheduler._participate_unanswered_thread",
                   return_value=None):
            result = task_continue_discussions()

        self.assertIn("id=10", result)
        self.assertIn("persona=student_02", result)


# ─────────────────────────────────────────────────────────────────────────────
# B. A separate unanswered/low-reply thread can be selected
# ─────────────────────────────────────────────────────────────────────────────
class TestUnansweredThreadParticipation(unittest.TestCase):

    def test_participate_skips_unknown_post_count(self):
        from elimu_ai.scheduler import _participate_unanswered_thread

        threads = [{"id": 10, "title": "Missing count", "opening_post": "Question"}]
        with patch("elimu_ai.tools.forum.get_unanswered_threads", return_value=threads), \
             patch("elimu_ai.scheduler._post_continuation_reply") as mock_reply:
            result = _participate_unanswered_thread()

        self.assertIsNone(result)
        mock_reply.assert_not_called()

    def test_step2_participates_in_unanswered_thread(self):
        from elimu_ai.scheduler import task_continue_discussions

        with patch("elimu_ai.scheduler._try_continue_existing_thread",
                   return_value=None), \
             patch("elimu_ai.scheduler._participate_unanswered_thread",
                   return_value="participated_unanswered_thread: id=71 posts=1 persona=student_03") as mock_part:
            result = task_continue_discussions()

        mock_part.assert_called_once()
        self.assertIn("participated_unanswered_thread", result)
        self.assertIn("id=71", result)

    def test_participate_selects_from_low_reply_threads(self):
        from elimu_ai.scheduler import _participate_unanswered_thread

        threads = [
            {"id": 10, "title": "Help with CBC Maths", "post_count": 1},
            {"id": 20, "title": "KCSE revision tips", "post_count": 2},
            {"id": 30, "title": "Heavily discussed topic", "post_count": 50},
        ]

        repo = MagicMock()
        repo.seconds_since_persona_last_posted_safe.return_value = None

        with patch("elimu_ai.tools.forum.get_unanswered_threads", return_value=threads), \
             patch("elimu_ai.scheduler._get_proactive_repo", return_value=repo), \
             patch("elimu_ai.scheduler._post_continuation_reply", return_value=True) as mock_reply:
            result = _participate_unanswered_thread()

        # Must have selected from threads with post_count 1–3 (not the 50-post one)
        mock_reply.assert_called_once()
        call_kwargs = mock_reply.call_args[1] if mock_reply.call_args[1] else {}
        call_args = mock_reply.call_args[0] if mock_reply.call_args[0] else []
        # thread_id must be 10 or 20, not 30
        tid = call_kwargs.get("thread_id") or (call_args[0] if call_args else None)
        self.assertIn(tid, [10, 20])

    def test_participate_skips_already_used_thread(self):
        from elimu_ai.scheduler import _participate_unanswered_thread

        threads = [
            {"id": 52, "title": "Thread already continued", "post_count": 1},
            {"id": 71, "title": "Fresh unanswered thread", "post_count": 1},
        ]

        repo = MagicMock()
        repo.seconds_since_persona_last_posted_safe.return_value = None

        with patch("elimu_ai.tools.forum.get_unanswered_threads", return_value=threads), \
             patch("elimu_ai.scheduler._get_proactive_repo", return_value=repo), \
             patch("elimu_ai.scheduler._post_continuation_reply", return_value=True) as mock_reply:
            result = _participate_unanswered_thread(skip_thread_id=52)

        # Must NOT have chosen thread 52
        call_kwargs = mock_reply.call_args[1] if mock_reply.call_args[1] else {}
        call_args = mock_reply.call_args[0] if mock_reply.call_args[0] else []
        tid = call_kwargs.get("thread_id") or (call_args[0] if call_args else None)
        self.assertEqual(tid, 71)

    def test_participate_returns_none_when_no_candidates(self):
        from elimu_ai.scheduler import _participate_unanswered_thread

        with patch("elimu_ai.tools.forum.get_unanswered_threads", return_value=[]):
            result = _participate_unanswered_thread()
        self.assertIsNone(result)

    def test_participate_returns_none_when_all_threads_too_busy(self):
        from elimu_ai.scheduler import _participate_unanswered_thread

        # All threads have post_count > 3 — not eligible
        threads = [{"id": i, "title": f"Busy thread {i}", "post_count": 10} for i in range(5)]
        with patch("elimu_ai.tools.forum.get_unanswered_threads", return_value=threads):
            result = _participate_unanswered_thread()
        self.assertIsNone(result)


# ─────────────────────────────────────────────────────────────────────────────
# C. Both behaviors coexist without one blocking the other
# ─────────────────────────────────────────────────────────────────────────────
class TestBothBehaviorsCoexist(unittest.TestCase):

    def test_both_step1_and_step2_run_when_both_succeed(self):
        from elimu_ai.scheduler import task_continue_discussions

        with patch("elimu_ai.scheduler._try_continue_existing_thread",
                   return_value="continued_existing_thread: id=52 posts=11/30 persona=teacher_01") as mock_cont, \
             patch("elimu_ai.scheduler._participate_unanswered_thread",
                   return_value="participated_unanswered_thread: id=71 posts=1 persona=student_03") as mock_part:
            result = task_continue_discussions()

        mock_cont.assert_called_once()
        mock_part.assert_called_once()
        self.assertIn("continued_existing_thread", result)
        self.assertIn("participated_unanswered_thread", result)

    def test_step2_runs_even_when_step1_finds_nothing(self):
        from elimu_ai.scheduler import task_continue_discussions

        with patch("elimu_ai.scheduler._try_continue_existing_thread",
                   return_value=None), \
             patch("elimu_ai.scheduler._participate_unanswered_thread",
                   return_value="participated_unanswered_thread: id=71 posts=1 persona=student_03") as mock_part:
            result = task_continue_discussions()

        mock_part.assert_called_once()
        self.assertIn("participated_unanswered_thread", result)

    def test_step1_runs_even_when_step2_finds_nothing(self):
        from elimu_ai.scheduler import task_continue_discussions

        with patch("elimu_ai.scheduler._try_continue_existing_thread",
                   return_value="continued_existing_thread: id=52 posts=11/30 persona=teacher_01") as mock_cont, \
             patch("elimu_ai.scheduler._participate_unanswered_thread",
                   return_value=None):
            result = task_continue_discussions()

        mock_cont.assert_called_once()
        self.assertIn("continued_existing_thread", result)

    def test_step2_receives_skip_thread_id_from_step1(self):
        """step2 must not re-use the thread continued in step1."""
        from elimu_ai.scheduler import task_continue_discussions

        with patch("elimu_ai.scheduler._try_continue_existing_thread",
                   return_value="continued_existing_thread: id=52 posts=11/30 persona=teacher_01"), \
             patch("elimu_ai.scheduler._participate_unanswered_thread") as mock_part:
            mock_part.return_value = None
            task_continue_discussions()

        call_kwargs = mock_part.call_args[1] if mock_part.call_args[1] else {}
        call_args   = mock_part.call_args[0] if mock_part.call_args[0] else []
        skip_id = call_kwargs.get("skip_thread_id") or (call_args[0] if call_args else None)
        self.assertEqual(skip_id, 52)

    def test_both_nothing_returns_graceful_message(self):
        from elimu_ai.scheduler import task_continue_discussions

        with patch("elimu_ai.scheduler._try_continue_existing_thread", return_value=None), \
             patch("elimu_ai.scheduler._participate_unanswered_thread", return_value=None):
            result = task_continue_discussions()

        self.assertIn("no threads requiring continuation", result)


# ─────────────────────────────────────────────────────────────────────────────
# D & E. persona_key preserved in both reply types
# ─────────────────────────────────────────────────────────────────────────────
class TestPersonaKeyPreserved(unittest.TestCase):

    def test_continuation_reply_uses_named_persona_key(self):
        from elimu_ai.scheduler import _post_continuation_reply
        from elimu_ai.personas.named import get_persona

        with patch("elimu_ai.tools.forum.post_moderated_reply") as mock_pmr, \
             patch("elimu_ai.gemini.generate", return_value="A meaningful educational reply about KCSE."):
            mock_pmr.return_value = True
            _post_continuation_reply(
                thread_id=52,
                thread_title="KCSE Mathematics revision",
                persona_name="teacher_01",
            )

        mock_pmr.assert_called_once()
        call_kwargs = mock_pmr.call_args[1] if mock_pmr.call_args[1] else {}
        self.assertEqual(call_kwargs.get("persona_key"), "teacher_01")
        # Confirm it's a valid NamedPersona key
        self.assertIsNotNone(get_persona("teacher_01"))

    def test_unanswered_thread_reply_uses_named_persona_key(self):
        from elimu_ai.scheduler import _participate_unanswered_thread

        threads = [{"id": 99, "title": "How do I prepare for KCSE?", "post_count": 1}]
        repo = MagicMock()
        repo.seconds_since_persona_last_posted_safe.return_value = None

        captured = {}

        def fake_post_continuation(thread_id, thread_title, persona_name, topic_context=""):
            captured["persona_name"] = persona_name
            captured["thread_id"] = thread_id
            return True

        with patch("elimu_ai.tools.forum.get_unanswered_threads", return_value=threads), \
             patch("elimu_ai.scheduler._get_proactive_repo", return_value=repo), \
             patch("elimu_ai.scheduler._post_continuation_reply",
                   side_effect=fake_post_continuation):
            _participate_unanswered_thread()

        from elimu_ai.personas.named import get_persona
        self.assertIn("persona_name", captured)
        key = captured["persona_name"]
        self.assertIsNotNone(get_persona(key),
                             f"Invalid persona_key used: {key!r}")
        # Must be a named key, not a role category
        role_names = {"teacher", "student", "community", "counsellor",
                      "parent", "librarian", "quizmaster"}
        self.assertNotIn(key, role_names)

    def test_persona_key_reaches_post_ai_answer(self):
        """End-to-end: persona_key flows from _post_continuation_reply to post_ai_answer."""
        from elimu_ai.scheduler import _post_continuation_reply

        with patch("elimu_ai.tools.forum.post_ai_answer") as mock_paa, \
             patch("elimu_ai.gemini.generate",
                   return_value="A meaningful educational reply about CBC Grade 6."), \
             patch("elimu_ai.tools.forum.moderate",
                   return_value="Content approved.") if False else \
             patch("elimu_ai.tools.moderation.moderate",
                   return_value="Content approved."):
            mock_paa.return_value = True
            with patch("elimu_ai.http_client.ElimuAPIClient.check_moderation",
                       return_value={"approved": True}):
                _post_continuation_reply(
                    thread_id=52,
                    thread_title="CBC Grade 6 learning activities",
                    persona_name="parent_01",
                )

        mock_paa.assert_called_once()
        call_kwargs = mock_paa.call_args[1] if mock_paa.call_args[1] else {}
        self.assertEqual(call_kwargs.get("persona_key"), "parent_01")


# ─────────────────────────────────────────────────────────────────────────────
# F. HTTP client receives persona_key
# ─────────────────────────────────────────────────────────────────────────────
class TestHTTPClientReceivesPersonaKey(unittest.TestCase):

    def test_post_answer_payload_has_persona_key(self):
        from elimu_ai.tools.forum import post_ai_answer
        with patch("elimu_ai.http_client.ElimuAPIClient.post_answer") as mock_pa:
            mock_pa.return_value = {}
            post_ai_answer(
                thread_id=52,
                content="AI reply content",
                persona_key="student_04",
            )
        mock_pa.assert_called_once()
        kwargs = mock_pa.call_args[1]
        self.assertEqual(kwargs.get("persona_key"), "student_04")


# ─────────────────────────────────────────────────────────────────────────────
# G. Existing idempotency preserved
# ─────────────────────────────────────────────────────────────────────────────
class TestIdempotencyPreserved(unittest.TestCase):

    def test_continuation_reply_has_stable_idempotency_key(self):
        """Two calls with the same thread+persona produce the same ikey prefix."""
        # The ikey is f"continuation-{thread_id}-{persona_name}-{uuid4}" so the
        # prefix is deterministic even if the suffix is random.
        # The important thing is it does NOT produce a different thread_id-based key.
        from elimu_ai.scheduler import _post_continuation_reply

        called_keys = []
        def capture_ikey(**kwargs):
            called_keys.append(kwargs.get("idempotency_key", ""))
            return True

        with patch("elimu_ai.tools.forum.post_moderated_reply",
                   side_effect=capture_ikey), \
             patch("elimu_ai.gemini.generate",
                   return_value="A meaningful educational reply."):
            _post_continuation_reply(52, "Test thread", "teacher_01")
            _post_continuation_reply(52, "Test thread", "teacher_01")

        # Both keys should start with the deterministic prefix
        for key in called_keys:
            self.assertTrue(
                key.startswith("continuation-52-teacher_01-"),
                f"Unexpected idempotency key: {key!r}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# H. Existing moderation preserved
# ─────────────────────────────────────────────────────────────────────────────
class TestModerationPreserved(unittest.TestCase):

    def test_spam_blocked_before_participation_reply(self):
        from elimu_ai.scheduler import _participate_unanswered_thread

        threads = [{"id": 100, "title": "Legit forum topic", "post_count": 1}]
        repo = MagicMock()
        repo.seconds_since_persona_last_posted_safe.return_value = None

        # Gemini returns spam — moderation must block it
        with patch("elimu_ai.tools.forum.get_unanswered_threads", return_value=threads), \
             patch("elimu_ai.scheduler._get_proactive_repo", return_value=repo), \
             patch("elimu_ai.gemini.generate",
                   return_value="buy now click here free money guaranteed income"), \
             patch("elimu_ai.tools.forum.post_ai_answer") as mock_post:
            result = _participate_unanswered_thread()

        # post_ai_answer must NOT have been called (moderation blocked it)
        mock_post.assert_not_called()

    def test_clean_content_passes_and_posts(self):
        from elimu_ai.scheduler import _participate_unanswered_thread

        threads = [{"id": 101, "title": "KCSE exam study strategies", "post_count": 1}]
        repo = MagicMock()
        repo.seconds_since_persona_last_posted_safe.return_value = None

        with patch("elimu_ai.tools.forum.get_unanswered_threads", return_value=threads), \
             patch("elimu_ai.scheduler._get_proactive_repo", return_value=repo), \
             patch("elimu_ai.gemini.generate",
                   return_value="Practicing past papers regularly is one of the most effective strategies for KCSE preparation."), \
             patch("elimu_ai.tools.forum.post_ai_answer", return_value=True) as mock_post, \
             patch("elimu_ai.http_client.ElimuAPIClient.check_moderation",
                   return_value={"approved": True}):
            result = _participate_unanswered_thread()

        mock_post.assert_called_once()
        self.assertIsNotNone(result)
        self.assertIn("participated_unanswered_thread", result)


# ─────────────────────────────────────────────────────────────────────────────
# I. Scheduler task registry not broken
# ─────────────────────────────────────────────────────────────────────────────
class TestSchedulerRegistryIntact(unittest.TestCase):

    def test_continue_discussions_still_in_registry(self):
        from elimu_ai.scheduler import _TASK_REGISTRY
        names = {name for name, _, _ in _TASK_REGISTRY}
        self.assertIn("continue_discussions", names)

    def test_all_existing_tasks_still_present(self):
        from elimu_ai.scheduler import _TASK_REGISTRY
        names = {name for name, _, _ in _TASK_REGISTRY}
        expected = {
            "answer_unanswered", "generate_discussions", "continue_discussions",
            "generate_article", "recommend_resources", "moderate_content",
            "catalog_sync", "health_check", "scheduler_self_heal",
            "retry_failed_queries",
        }
        missing = expected - names
        self.assertEqual(missing, set(), f"Tasks missing from registry: {missing}")

    def test_participate_unanswered_thread_is_callable(self):
        from elimu_ai.scheduler import _participate_unanswered_thread
        self.assertTrue(callable(_participate_unanswered_thread))


if __name__ == "__main__":
    unittest.main()
