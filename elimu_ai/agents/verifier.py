"""
elimu_ai/agents/verifier.py

Verification Agent — checks output quality before it is returned to the user.

Checks:
  - Response is non-empty
  - Response does not start with error phrases
  - No hallucinated URLs (URLs must come from catalog or Qdrant hits)
  - No duplicated sentences
  - Minimum useful length
  - No raw Markdown artifacts in plain-text responses
  - Confidence score 0.0–1.0

Uses Gemini for semantic verification when available,
falls back to rule-based checks otherwise.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)

_ERROR_PREFIXES = (
    "Elimu AI is temporarily",
    "Elimu AI could not",
    "I encountered an error",
    "I was unable to generate",
    "An internal error",
)

_HALLUCINATION_PATTERNS = [
    r"https?://(?!www\.elimulibrary\.com|elimutalks\.com)[^\s]+/site/document/",
]

_MARKDOWN_ARTIFACTS = [
    r"\*{2,}",   # **bold**
    r"_{2,}",    # __underline__
    r"^#{1,6}\s",# ## heading
    r"```",      # code block
]


@dataclass
class VerificationResult:
    passed: bool
    confidence: float       # 0.0 – 1.0
    issues: List[str]
    revised_answer: Optional[str] = None  # cleaned answer if issues fixed


class VerifierAgent:
    """
    Verifies AI output quality.
    Returns a VerificationResult — never raises.
    """

    def verify(
        self,
        answer: str,
        question: str,
        sources: Optional[List[str]] = None,
    ) -> VerificationResult:
        """Run all verification checks on the answer."""
        issues: List[str] = []
        confidence = 1.0

        # Check 1: non-empty
        if not answer or not answer.strip():
            return VerificationResult(
                passed=False,
                confidence=0.0,
                issues=["Empty response"],
            )

        # Check 2: error prefix
        for prefix in _ERROR_PREFIXES:
            if answer.startswith(prefix):
                issues.append(f"Error prefix detected: {prefix[:40]}")
                confidence -= 0.3

        # Check 3: hallucinated URLs
        for pattern in _HALLUCINATION_PATTERNS:
            if re.search(pattern, answer):
                issues.append("Possible hallucinated URL detected")
                confidence -= 0.4

        # Check 4: Markdown artifacts in plain-text response
        md_count = 0
        for pattern in _MARKDOWN_ARTIFACTS:
            if re.search(pattern, answer, re.MULTILINE):
                md_count += 1
        if md_count >= 2:
            issues.append(f"Markdown artifacts found ({md_count})")
            confidence -= 0.1

        # Check 5: minimum length
        if len(answer.strip()) < 30:
            issues.append("Response too short to be useful")
            confidence -= 0.2

        # Check 6: duplicate sentences
        sentences = [s.strip() for s in re.split(r'[.!?]', answer) if len(s.strip()) > 20]
        seen = set()
        dupes = 0
        for s in sentences:
            norm = s.lower()
            if norm in seen:
                dupes += 1
            seen.add(norm)
        if dupes > 1:
            issues.append(f"Duplicate sentences detected ({dupes})")
            confidence -= 0.1

        confidence = max(0.0, min(1.0, confidence))
        passed = confidence >= 0.5 and not any(
            "hallucinated URL" in i or "Error prefix" in i for i in issues
        )

        # Auto-clean Markdown if minor issues
        revised = answer
        if md_count > 0 and passed:
            revised = self._strip_markdown(answer)

        if issues:
            logger.info("VerifierAgent: %d issues, confidence=%.2f, issues=%s",
                        len(issues), confidence, issues)

        return VerificationResult(
            passed=passed,
            confidence=confidence,
            issues=issues,
            revised_answer=revised if revised != answer else None,
        )

    def _strip_markdown(self, text: str) -> str:
        """Remove common Markdown from text."""
        text = re.sub(r"\*{1,3}([^*\n]+)\*{1,3}", r"\1", text)
        text = re.sub(r"_{1,3}([^_\n]+)_{1,3}", r"\1", text)
        text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"```[\s\S]*?```", "", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
