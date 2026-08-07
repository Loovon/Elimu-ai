"""
elimu_ai/natural_language.py

Natural Language Writer — rewrites AI output to sound like a real educator.

Rules enforced:
  - No Markdown artifacts
  - No robotic bullet points or headers in conversational responses
  - No repeated opening sentences
  - No duplicated recommendations
  - No "Here are the results:" type intros unless genuinely listing documents
  - Responses feel warm, knowledgeable, and human
  - URLs are preserved exactly — never invented

Uses Gemini when available; falls back to rule-based cleaning otherwise.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

_REWRITE_PROMPT = """\
You are a senior Kenyan educator rewriting an AI response so it sounds natural and human.

Rules:
- Write in plain text only. No Markdown, no asterisks, no bullet points, no headers.
- Sound like a real teacher talking to a student — warm, helpful, knowledgeable.
- Do not repeat the question back.
- Do not start with "Certainly!", "Sure!", "Of course!" or similar filler phrases.
- Do not duplicate any sentence.
- Keep all URLs exactly as they are — do not invent or modify them.
- Keep all prices, titles, and document names exactly as they are.
- If the response contains a list of documents, format each one naturally
  on its own line with the URL below it.
- Maximum length: 400 words for explanations, unlimited for document lists.
- Do not add any new information that was not in the original response.

Original response to rewrite:
{raw}

Question that was asked:
{question}

Rewrite now (plain text only):
"""

_ROBOTIC_OPENERS = [
    r"^here are the (best|most relevant|top|matching) materials",
    r"^i found the following",
    r"^based on your query",
    r"^certainly[,!.]",
    r"^sure[,!.]",
    r"^of course[,!.]",
    r"^absolutely[,!.]",
    r"^great question[,!.]",
    r"^as an ai",
    r"^i am an ai",
]


class NaturalLanguageWriter:
    """Rewrites AI output to sound like a human educator."""

    def rewrite(
        self,
        raw: str,
        persona: str = "teacher",
        question: str = "",
        use_gemini: bool = True,
    ) -> str:
        """
        Rewrite the raw output.
        Returns the rewritten text — never raises.
        """
        if not raw or not raw.strip():
            return raw

        # For document lists (catalog results), only do light cleaning
        if self._is_document_list(raw):
            return self._light_clean(raw)

        # For explanations, use Gemini rewrite if available
        if use_gemini:
            try:
                rewritten = self._gemini_rewrite(raw, question)
                if rewritten and not rewritten.startswith("Elimu AI"):
                    return self._light_clean(rewritten)
            except Exception as exc:
                logger.debug("NaturalLanguageWriter: Gemini rewrite failed: %s", exc)

        # Rule-based cleaning
        return self._rule_based_clean(raw)

    def _gemini_rewrite(self, raw: str, question: str) -> str:
        """Use Gemini to rewrite in natural educator tone."""
        from elimu_ai.gemini import generate

        # Only rewrite if it looks like an explanation (not a document list)
        prompt = _REWRITE_PROMPT.format(
            raw=raw[:1500],
            question=question[:200],
        )
        result = generate(prompt)
        return result

    def _is_document_list(self, text: str) -> bool:
        """True if the text is primarily a catalog document listing."""
        return (
            "elimulibrary.com/site/document/" in text
            or "Here are the best matching materials" in text
            or "most relevant materials for" in text.lower()
        )

    def _light_clean(self, text: str) -> str:
        """Minimal cleaning — preserve URLs and document data exactly."""
        # Strip obvious Markdown
        text = re.sub(r"\*{2,}([^*\n]+)\*{2,}", r"\1", text)
        text = re.sub(r"_{2,}([^_\n]+)_{2,}", r"\1", text)
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"```[\s\S]*?```", "", text)
        # Collapse excess blank lines
        text = re.sub(r"\n{4,}", "\n\n\n", text)
        return text.strip()

    def _rule_based_clean(self, text: str) -> str:
        """Full rule-based clean for conversational responses."""
        # Strip Markdown
        text = re.sub(r"\*{1,3}([^*\n]+)\*{1,3}", r"\1", text)
        text = re.sub(r"_{1,3}([^_\n]+)_{1,3}", r"\1", text)
        text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"```[\s\S]*?```", "", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)

        # Remove robotic openers
        for pattern in _ROBOTIC_OPENERS:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.MULTILINE)

        # Remove duplicate sentences
        text = self._deduplicate_sentences(text)

        # Collapse blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()

    def _deduplicate_sentences(self, text: str) -> str:
        """Remove duplicate sentences while preserving order."""
        sentences = re.split(r"(?<=[.!?])\s+", text)
        seen = set()
        unique = []
        for s in sentences:
            norm = s.lower().strip()
            if norm and norm not in seen:
                seen.add(norm)
                unique.append(s)
        return " ".join(unique)
