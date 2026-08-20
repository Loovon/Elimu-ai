"""
elimu_ai/personas/ — Per-persona configuration.

Also re-exports the legacy string constants (TEACHER, LIBRARIAN, etc.)
so existing code like forum.py and scheduler.py continues to work.

Phase 2: also exports the 36 NamedPersona registry from named.py.
"""
from elimu_ai.personas.registry import PersonaRegistry, PersonaConfig, persona_registry
from elimu_ai.personas.named import (
    NamedPersona,
    get_persona,
    get_persona_by_username,
    get_personas_by_category,
    all_active_personas,
    all_community_personas,
    TOTAL_PERSONAS,
)

# ── Legacy constants (backward-compatible) ───────────────────────────────────
TEACHER:    str = "TeacherAI"
LIBRARIAN:  str = "LibrarianAI"
QUIZMASTER: str = "QuizMasterAI"
STUDENT:    str = "StudentAI"
COMMUNITY:  str = "CommunityAI"
MODERATOR:  str = "ModeratorAI"

__all__ = [
    "PersonaRegistry", "PersonaConfig", "persona_registry",
    "NamedPersona",
    "get_persona", "get_persona_by_username",
    "get_personas_by_category", "all_active_personas",
    "all_community_personas", "TOTAL_PERSONAS",
    "TEACHER", "LIBRARIAN", "QUIZMASTER", "STUDENT", "COMMUNITY", "MODERATOR",
]
