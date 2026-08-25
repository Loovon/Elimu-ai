"""
elimu_ai/tests/test_personas.py

Named-persona system tests (Phase 2 requirement).

Tests:
  1.  Exactly 36 active named personas
  2.  Every persona has a unique stable key
  3.  Every persona has a unique public display_name
  4.  Every persona has a unique username
  5.  Persona lookup is deterministic (same key → same object)
  6.  Persona lookup by username works
  7.  Persona lookup by category works
  8.  all_community_personas excludes moderators
  9.  Persona selection returns a valid NamedPersona key
  10. Persona cooldown still works (LRU rotation)
  11. New thread receives persona_key in API payload
  12. Reply receives persona_key in API payload
  13. Continuation reply receives persona_key in API payload
  14. save_forum_post passes persona_key to http_client
  15. post_ai_answer passes persona_key to http_client
  16. post_moderated_reply passes persona_key through to post_ai_answer
  17. Unknown persona_key raises ValueError (no silent fallback)
  18. Worker restart does not reset persona counts (keys are stable)
  19. No code path calls LLM for persona selection
  20. All personas have non-empty voice instructions
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch, call


# ─────────────────────────────────────────────────────────────────────────────
# 1. Exactly 36 active named personas
# ─────────────────────────────────────────────────────────────────────────────
class TestPersonaCount(unittest.TestCase):

    def test_exactly_36_personas_defined(self):
        from elimu_ai.personas.named import _PERSONAS
        self.assertEqual(len(_PERSONAS), 36)

    def test_total_personas_constant_is_36(self):
        from elimu_ai.personas.named import TOTAL_PERSONAS
        self.assertEqual(TOTAL_PERSONAS, 36)

    def test_all_active_returns_36(self):
        from elimu_ai.personas.named import all_active_personas
        self.assertEqual(len(all_active_personas()), 36)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Every persona has a unique stable key
# ─────────────────────────────────────────────────────────────────────────────
class TestPersonaUniqueness(unittest.TestCase):

    def test_all_keys_are_unique(self):
        from elimu_ai.personas.named import _PERSONAS
        keys = [p.key for p in _PERSONAS]
        self.assertEqual(len(keys), len(set(keys)), "Duplicate keys found")

    def test_all_display_names_are_unique(self):
        from elimu_ai.personas.named import _PERSONAS
        names = [p.display_name for p in _PERSONAS]
        self.assertEqual(len(names), len(set(names)), "Duplicate display_names found")

    def test_all_usernames_are_unique(self):
        from elimu_ai.personas.named import _PERSONAS
        usernames = [p.username for p in _PERSONAS]
        self.assertEqual(
            len(usernames), len(set(usernames)), "Duplicate usernames found"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4–7. Persona lookup
# ─────────────────────────────────────────────────────────────────────────────
class TestPersonaLookup(unittest.TestCase):

    def test_get_persona_by_key_returns_correct_object(self):
        from elimu_ai.personas.named import get_persona
        p = get_persona("student_01")
        self.assertIsNotNone(p)
        self.assertEqual(p.key, "student_01")
        self.assertEqual(p.username, "brian_otieno")
        self.assertEqual(p.display_name, "Brian Otieno")
        self.assertEqual(p.role, "Student")

    def test_get_persona_is_deterministic(self):
        from elimu_ai.personas.named import get_persona
        p1 = get_persona("teacher_01")
        p2 = get_persona("teacher_01")
        self.assertIs(p1, p2)

    def test_get_persona_unknown_key_returns_none(self):
        from elimu_ai.personas.named import get_persona
        self.assertIsNone(get_persona("nonexistent_key"))

    def test_get_persona_by_username(self):
        from elimu_ai.personas.named import get_persona_by_username
        p = get_persona_by_username("grace_wanjiku")
        self.assertIsNotNone(p)
        self.assertEqual(p.key, "teacher_01")

    def test_get_personas_by_category_teacher(self):
        from elimu_ai.personas.named import get_personas_by_category
        teachers = get_personas_by_category("teacher")
        self.assertGreaterEqual(len(teachers), 1)
        for t in teachers:
            self.assertEqual(t.role_category, "teacher")

    def test_get_personas_by_category_student(self):
        from elimu_ai.personas.named import get_personas_by_category
        students = get_personas_by_category("student")
        self.assertGreaterEqual(len(students), 1)

    def test_all_community_personas_excludes_moderators(self):
        from elimu_ai.personas.named import all_community_personas
        personas = all_community_personas()
        for p in personas:
            self.assertNotEqual(
                p.role_category, "moderator",
                f"{p.key} is a moderator but appears in community list"
            )
        self.assertGreater(len(personas), 0)


# ─────────────────────────────────────────────────────────────────────────────
# 9. Persona selection returns a valid NamedPersona key
# ─────────────────────────────────────────────────────────────────────────────
class TestPersonaSelection(unittest.TestCase):

    def test_select_persona_returns_valid_key(self):
        from elimu_ai.scheduler import _select_persona
        from elimu_ai.personas.named import get_persona

        repo = MagicMock()
        repo.seconds_since_persona_last_posted_safe.return_value = None  # all unused

        key, display = _select_persona(repo, persona_cooldown=3600)
        self.assertIsNotNone(get_persona(key), f"Invalid persona key returned: {key!r}")
        self.assertIsInstance(display, str)
        self.assertGreater(len(display), 0)

    def test_select_persona_never_returns_role_category_name(self):
        """Selection must return a named key like 'student_01', not a role like 'student'."""
        from elimu_ai.scheduler import _select_persona

        repo = MagicMock()
        repo.seconds_since_persona_last_posted_safe.return_value = 99999

        role_names = {"teacher", "student", "community", "counsellor",
                      "parent", "librarian", "quizmaster", "moderator"}
        for _ in range(10):
            key, _ = _select_persona(repo, persona_cooldown=1)
            self.assertNotIn(
                key, role_names,
                f"_select_persona returned a role category name: {key!r}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 10. Persona cooldown / LRU rotation
# ─────────────────────────────────────────────────────────────────────────────
class TestPersonaCooldown(unittest.TestCase):

    def test_first_time_persona_has_priority_over_rested_persona(self):
        from elimu_ai.scheduler import _select_persona
        from elimu_ai.personas.named import all_community_personas, get_persona

        all_keys = [p.key for p in all_community_personas()]
        # Simulate: all used except the last one (never posted)
        never_used_key = all_keys[-1]

        def fake_seconds(pkey):
            if pkey == never_used_key:
                return None   # never posted
            return 99999      # everyone else has rested

        repo = MagicMock()
        repo.seconds_since_persona_last_posted_safe.side_effect = fake_seconds

        key, _ = _select_persona(repo, persona_cooldown=3600)
        self.assertEqual(key, never_used_key)

    def test_all_on_cooldown_returns_longest_inactive(self):
        from elimu_ai.scheduler import _select_persona
        from elimu_ai.personas.named import all_community_personas

        all_keys = [p.key for p in all_community_personas()]
        # The second key has been inactive the longest (10000s)
        target_key = all_keys[1]

        def fake_seconds(pkey):
            if pkey == target_key:
                return 100     # under cooldown but longest inactive in fallback
            return 50          # everyone else shorter

        repo = MagicMock()
        repo.seconds_since_persona_last_posted_safe.side_effect = fake_seconds

        key, _ = _select_persona(repo, persona_cooldown=200)  # all under cooldown
        self.assertEqual(key, target_key)

    def test_selection_rotates_over_runs(self):
        from elimu_ai.scheduler import _select_persona
        from elimu_ai.personas.named import all_community_personas

        all_keys = [p.key for p in all_community_personas()]
        selected = set()

        # Simulate different elapsed times so the "longest inactive" changes each call
        for i in range(len(all_keys)):
            target_key = all_keys[i]

            def make_secs(tkey):
                def fake_secs(pkey):
                    # The target key has the highest elapsed time → selected
                    if pkey == tkey:
                        return 99999
                    return 100   # others just expired cooldown but shorter inactive
                return fake_secs

            repo = MagicMock()
            repo.seconds_since_persona_last_posted_safe.side_effect = make_secs(target_key)
            key, _ = _select_persona(repo, persona_cooldown=50)
            selected.add(key)

        self.assertGreaterEqual(len(selected), 2, "Persona rotation not working")


# ─────────────────────────────────────────────────────────────────────────────
# 11–16. persona_key flows through API payloads
# ─────────────────────────────────────────────────────────────────────────────
class TestPersonaKeyInAPIPayloads(unittest.TestCase):

    def test_save_forum_post_passes_persona_key_to_http_client(self):
        from elimu_ai.tools.forum import save_forum_post
        with patch("elimu_ai.http_client.ElimuAPIClient.create_discussion") as mock_cd:
            mock_cd.return_value = {"slug": "test", "category_name": "revision"}
            save_forum_post(
                "Test Title", "Body", "revision",
                persona_key="teacher_01",
            )
        mock_cd.assert_called_once()
        kwargs = mock_cd.call_args[1]
        self.assertEqual(kwargs.get("persona_key"), "teacher_01")

    def test_post_ai_answer_passes_persona_key_to_http_client(self):
        from elimu_ai.tools.forum import post_ai_answer
        with patch("elimu_ai.http_client.ElimuAPIClient.post_answer") as mock_pa:
            mock_pa.return_value = {}
            post_ai_answer(
                thread_id=5,
                content="Test answer",
                persona_key="student_01",
            )
        mock_pa.assert_called_once()
        kwargs = mock_pa.call_args[1]
        self.assertEqual(kwargs.get("persona_key"), "student_01")

    def test_post_moderated_reply_passes_persona_key_through(self):
        from elimu_ai.tools.forum import post_moderated_reply
        with patch("elimu_ai.tools.forum.post_ai_answer") as mock_pa:
            mock_pa.return_value = True
            post_moderated_reply(
                thread_id=7,
                content="A clean educational reply about KCSE Mathematics.",
                persona_name="librarian_01",
                persona_key="librarian_01",
            )
        mock_pa.assert_called_once()
        kwargs = mock_pa.call_args[1]
        self.assertEqual(kwargs.get("persona_key"), "librarian_01")

    def test_create_discussion_http_payload_includes_persona_key(self):
        from elimu_ai.http_client import ElimuAPIClient
        client = ElimuAPIClient(base_url="http://example.com")

        with patch.object(client, "_request") as mock_req:
            mock_req.return_value = {"slug": "test", "id": 1}
            client.create_discussion(
                title="Test", body="Body", category="kcse",
                persona_key="counsellor_01",
            )
        mock_req.assert_called_once()
        # _request is called as: _request("POST", path, payload, idempotency_key=key)
        args = mock_req.call_args
        payload = args[0][2] if len(args[0]) > 2 else args[1].get("payload")
        self.assertIsNotNone(payload, "payload not found in _request call")
        self.assertEqual(payload.get("persona_key"), "counsellor_01")

    def test_post_answer_http_payload_includes_persona_key(self):
        from elimu_ai.http_client import ElimuAPIClient
        client = ElimuAPIClient(base_url="http://example.com")

        with patch.object(client, "_request") as mock_req:
            mock_req.return_value = {}
            client.post_answer(
                thread_id=9, content="Answer text",
                persona_key="parent_02",
            )
        mock_req.assert_called_once()
        args = mock_req.call_args
        payload = args[0][2] if len(args[0]) > 2 else args[1].get("payload")
        self.assertIsNotNone(payload, "payload not found in _request call")
        self.assertEqual(payload.get("persona_key"), "parent_02")

    def test_without_persona_key_payload_still_works(self):
        """Backward compat: persona_key is optional — no error if omitted."""
        from elimu_ai.http_client import ElimuAPIClient
        client = ElimuAPIClient(base_url="http://example.com")

        with patch.object(client, "_request") as mock_req:
            mock_req.return_value = {"slug": "test"}
            client.create_discussion(title="T", body="B", category="cbc")
        args = mock_req.call_args
        payload = args[0][2] if len(args[0]) > 2 else args[1].get("payload")
        self.assertIsNotNone(payload)
        self.assertNotIn("persona_key", payload)

    def test_unknown_persona_key_is_rejected_before_request(self):
        from elimu_ai.http_client import ElimuAPIClient
        client = ElimuAPIClient(base_url="http://example.com")

        with patch.object(client, "_request") as mock_req:
            with self.assertRaises(ValueError):
                client.post_answer(
                    thread_id=9,
                    content="Answer text",
                    persona_key="does_not_exist",
                )
        mock_req.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 17. Unknown persona_key raises ValueError
# ─────────────────────────────────────────────────────────────────────────────
class TestPersonaKeyValidation(unittest.TestCase):

    def test_create_discussion_with_unknown_key_raises(self):
        from elimu_ai.scheduler import _create_discussion_as_persona
        with self.assertRaises(ValueError):
            _create_discussion_as_persona(
                persona_key="does_not_exist",
                persona_display="Unknown",
                topic="Some topic",
            )

    def test_post_continuation_with_unknown_key_returns_false(self):
        from elimu_ai.scheduler import _post_continuation_reply
        result = _post_continuation_reply(
            thread_id=99,
            thread_title="Some thread",
            persona_name="does_not_exist",
        )
        self.assertFalse(result)


# ─────────────────────────────────────────────────────────────────────────────
# 18. Stable keys survive import (worker restart simulation)
# ─────────────────────────────────────────────────────────────────────────────
class TestPersonaStability(unittest.TestCase):

    def test_same_key_always_returns_same_display_name(self):
        import importlib
        import elimu_ai.personas.named as named_module

        p1 = named_module.get_persona("teacher_01")
        # Reload the module (simulates worker restart re-importing)
        importlib.reload(named_module)
        p2 = named_module.get_persona("teacher_01")

        self.assertEqual(p1.display_name, p2.display_name)
        self.assertEqual(p1.username, p2.username)

    def test_no_random_usernames_in_registry(self):
        """All usernames must be deterministic strings, not random."""
        from elimu_ai.personas.named import _PERSONAS
        import re
        # No UUID-like patterns or random tokens
        uuid_pattern = re.compile(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
        )
        for p in _PERSONAS:
            self.assertFalse(
                uuid_pattern.search(p.username),
                f"Random-looking username for {p.key}: {p.username}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 19. No LLM call for persona selection
# ─────────────────────────────────────────────────────────────────────────────
class TestNoLLMForPersonaSelection(unittest.TestCase):

    def test_select_persona_does_not_call_gemini(self):
        from elimu_ai.scheduler import _select_persona
        repo = MagicMock()
        repo.seconds_since_persona_last_posted_safe.return_value = 99999
        with patch("elimu_ai.gemini.generate") as mock_gen:
            _select_persona(repo, persona_cooldown=1)
        mock_gen.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 20. All personas have non-empty voice instructions
# ─────────────────────────────────────────────────────────────────────────────
class TestPersonaVoice(unittest.TestCase):

    def test_all_personas_have_non_empty_voice(self):
        from elimu_ai.personas.named import _PERSONAS
        for p in _PERSONAS:
            self.assertTrue(
                p.voice and len(p.voice.strip()) > 10,
                f"Persona {p.key} has empty/short voice: {p.voice!r}"
            )

    def test_all_personas_have_non_empty_bio(self):
        from elimu_ai.personas.named import _PERSONAS
        for p in _PERSONAS:
            self.assertTrue(
                p.bio and len(p.bio.strip()) > 5,
                f"Persona {p.key} has empty bio"
            )

    def test_all_personas_have_non_empty_role(self):
        from elimu_ai.personas.named import _PERSONAS
        for p in _PERSONAS:
            self.assertTrue(
                p.role and len(p.role.strip()) > 0,
                f"Persona {p.key} has empty role"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Full integration: scheduler selects named persona and passes key to API
# ─────────────────────────────────────────────────────────────────────────────
class TestSchedulerUsesNamedPersona(unittest.TestCase):

    def test_generate_discussions_proactive_passes_persona_key(self):
        """End-to-end: scheduler → _create_discussion_as_persona → save_forum_post → HTTP client."""
        from elimu_ai.scheduler import task_generate_discussions
        from elimu_ai.personas.named import get_persona

        repo = MagicMock()
        repo.count_today_safe.return_value = 0
        repo.seconds_since_last_safe.return_value = 99999
        repo.seconds_since_persona_last_posted_safe.return_value = None  # all unused
        repo.get_recent_topics_safe.return_value = []
        repo.log_discussion.return_value = None

        captured = {}

        def fake_create(persona_key, persona_display, topic):
            captured["persona_key"] = persona_key
            captured["persona_display"] = persona_display
            return "created: /thread/test/"

        with patch("elimu_ai.tools.forum.get_unanswered_threads", return_value=[]), \
             patch("elimu_ai.scheduler._try_continue_existing_thread", return_value=None), \
             patch("elimu_ai.scheduler._get_proactive_repo", return_value=repo), \
             patch("elimu_ai.scheduler._find_relevant_thread_for_topic", return_value=None), \
             patch("elimu_ai.scheduler._create_discussion_as_persona",
                   side_effect=fake_create):
            result = task_generate_discussions()

        # Verify a named persona key was selected (not a role category name)
        self.assertIn("persona_key", captured)
        key = captured["persona_key"]
        role_names = {"teacher", "student", "community", "counsellor",
                      "parent", "librarian", "quizmaster"}
        self.assertNotIn(key, role_names, f"Role name used instead of named key: {key!r}")
        self.assertIsNotNone(get_persona(key), f"Invalid persona_key selected: {key!r}")
        self.assertIn("created_proactive_discussion", result)


if __name__ == "__main__":
    unittest.main()
