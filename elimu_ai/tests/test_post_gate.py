from __future__ import annotations

from elimu_ai.community_tasks import should_post
from elimu_ai.config import parse_duration_seconds


def test_parse_duration_seconds_supports_human_units():
    assert parse_duration_seconds("12h") == 43200
    assert parse_duration_seconds("2h") == 7200
    assert parse_duration_seconds("30m") == 1800
    assert parse_duration_seconds("3d") == 259200
    assert parse_duration_seconds("45s") == 45


def test_should_post_requires_all_gates_open():
    ok, reason = should_post(
        function_cooldown_ready=True,
        persona_cooldown_ready=False,
        not_duplicate=True,
        under_daily_cap=True,
        under_per_thread_cap=True,
    )
    assert ok is False
    assert reason == "blocked: persona cooldown"

    ok, reason = should_post(
        function_cooldown_ready=True,
        persona_cooldown_ready=True,
        not_duplicate=False,
        under_daily_cap=True,
        under_per_thread_cap=True,
    )
    assert ok is False
    assert reason == "blocked: duplicate"

    ok, reason = should_post(
        function_cooldown_ready=True,
        persona_cooldown_ready=True,
        not_duplicate=True,
        under_daily_cap=True,
        under_per_thread_cap=True,
    )
    assert ok is True
    assert reason == "allowed"


def test_persona_prompt_uses_role_and_identity():
    from elimu_ai.personas.named import get_persona

    persona = get_persona("teacher_01")
    prompt = (
        f"{persona.voice}\n\n"
        f"Role: {persona.role}\n"
        f"Name: {persona.display_name}\n"
        "Share a practical classroom insight."
    )

    assert "Teacher" in prompt
    assert "Grace Wanjiku" in prompt
    assert "classroom" in prompt.lower()
