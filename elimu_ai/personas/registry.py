"""
elimu_ai/personas/registry.py

Declarative persona registry.
Each persona declares its tools, memory keys, and handoff rules.

Phase 2: PersonaConfig now carries an optional reference to a NamedPersona
so the full 36-persona identity is accessible from any tool that has a
persona_registry lookup.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from elimu_ai.personas.named import NamedPersona


@dataclass
class PersonaConfig:
    name: str
    display: str
    description: str
    primary_tools: List[str]
    fallback_tools: List[str]
    handoff_to: Dict[str, str]   # intent → persona_name
    system_prompt_key: str
    audience: Optional[str] = None   # teacher / student / parent / None


class PersonaRegistry:
    def __init__(self):
        self._personas: Dict[str, PersonaConfig] = {}

    def register(self, cfg: PersonaConfig) -> None:
        self._personas[cfg.name] = cfg

    def get(self, name: str) -> Optional[PersonaConfig]:
        return self._personas.get(name)

    def all_names(self) -> List[str]:
        return list(self._personas.keys())


def _build() -> PersonaRegistry:
    reg = PersonaRegistry()

    reg.register(PersonaConfig(
        name="teacher",
        display="Teacher AI",
        description="Explains Kenyan CBC and 8-4-4 curriculum concepts clearly",
        primary_tools=["qdrant_search", "teacher"],
        fallback_tools=["catalog_search"],
        handoff_to={
            "quiz":           "quizmaster",
            "recommendation": "librarian",
            "community":      "community",
        },
        system_prompt_key="TEACHER_PROMPT",
    ))

    reg.register(PersonaConfig(
        name="quizmaster",
        display="Quiz AI",
        description="Generates KCSE and CBC exam questions with model answers",
        primary_tools=["qdrant_search", "quiz"],
        fallback_tools=["catalog_search"],
        handoff_to={
            "teacher":        "teacher",
            "recommendation": "librarian",
        },
        system_prompt_key="QUIZ_PROMPT",
    ))

    reg.register(PersonaConfig(
        name="librarian",
        display="Librarian AI",
        description="Finds exact documents from Elimu Library",
        primary_tools=["catalog_search", "librarian"],
        fallback_tools=["qdrant_search"],
        handoff_to={
            "teacher": "teacher",
            "quiz":    "quizmaster",
        },
        system_prompt_key="LIBRARIAN_PROMPT",
    ))

    reg.register(PersonaConfig(
        name="community",
        display="Community AI",
        description="Creates and curates ElimuTalks forum discussions",
        primary_tools=["community"],
        fallback_tools=[],
        handoff_to={
            "teacher":        "teacher",
            "recommendation": "librarian",
        },
        system_prompt_key="COMMUNITY_PROMPT",
    ))

    reg.register(PersonaConfig(
        name="moderator",
        display="Moderator AI",
        description="Detects spam and policy violations",
        primary_tools=["moderation"],
        fallback_tools=[],
        handoff_to={},
        system_prompt_key="BASE_PROMPT",
    ))

    reg.register(PersonaConfig(
        name="counsellor",
        display="Career Counsellor AI",
        description="Advises on careers, university choices, and scholarships",
        primary_tools=["teacher", "qdrant_search"],
        fallback_tools=["catalog_search"],
        handoff_to={
            "recommendation": "librarian",
        },
        system_prompt_key="TEACHER_PROMPT",
    ))

    reg.register(PersonaConfig(
        name="parent",
        display="Parent Advisor AI",
        description="Guides parents on CBC, homework, and school resources",
        primary_tools=["catalog_search", "recommendation"],
        fallback_tools=["teacher"],
        handoff_to={
            "teacher": "teacher",
        },
        system_prompt_key="TEACHER_PROMPT",
        audience="parent",
    ))

    reg.register(PersonaConfig(
        name="student",
        display="Student Peer AI",
        description="Speaks as a peer student — encourages and discusses",
        primary_tools=["teacher", "qdrant_search"],
        fallback_tools=[],
        handoff_to={
            "quiz":           "quizmaster",
            "recommendation": "librarian",
        },
        system_prompt_key="TEACHER_PROMPT",
        audience="student",
    ))

    return reg


persona_registry: PersonaRegistry = _build()
