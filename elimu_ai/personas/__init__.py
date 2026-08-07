"""
elimu_ai/personas/ — Per-persona configuration.

Also re-exports the legacy string constants (TEACHER, LIBRARIAN, etc.)
so existing code like forum.py and scheduler.py continues to work.
"""
from elimu_ai.personas.registry import PersonaRegistry, PersonaConfig, persona_registry

# ── Legacy constants (backward-compatible) ───────────────────────────────────
TEACHER:    str = "TeacherAI"
LIBRARIAN:  str = "LibrarianAI"
QUIZMASTER: str = "QuizMasterAI"
STUDENT:    str = "StudentAI"
COMMUNITY:  str = "CommunityAI"
MODERATOR:  str = "ModeratorAI"

__all__ = [
    "PersonaRegistry", "PersonaConfig", "persona_registry",
    "TEACHER", "LIBRARIAN", "QUIZMASTER", "STUDENT", "COMMUNITY", "MODERATOR",
]
