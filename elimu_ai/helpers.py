"""
elimu_ai/helpers.py

Pure utility functions — no I/O, no network calls.
Responsibilities:
  - clean_answer()     strip Markdown from Gemini output
  - referral_url()     append referral tracking to a URL
  - rewrite_links()    rewrite all URLs in text with referral params
  - search_url()       build an Elimu Library search URL
"""

from __future__ import annotations

import re
from urllib.parse import (
    parse_qs,
    quote,
    urlencode,
    urlparse,
    urlunparse,
)

from elimu_ai.config import REFERRAL_ID

_ELIMU_SEARCH_BASE = "https://www.elimulibrary.com/?s="
_REF_PARAM = "ref=elimutalks"
_RETURN_PARAM = "return_url=https%3A%2F%2Felimitalks.com"


# ── Text cleaning ─────────────────────────────────────────────────────────────

def clean_answer(text: str) -> str:
    """Strip common Markdown formatting from Gemini output."""
    if not text:
        return ""
    text = re.sub(r"\*{1,3}([^*\n]+)\*{1,3}", r"\1", text)   # bold / italic
    text = re.sub(r"_{1,3}([^_\n]+)_{1,3}", r"\1", text)      # underline / italic
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE) # headings
    text = re.sub(r"```[\s\S]*?```", "", text)                  # code blocks
    text = re.sub(r"`([^`]+)`", r"\1", text)                    # inline code
    text = re.sub(r"\n{3,}", "\n\n", text)                      # excess blank lines
    return text.strip()


# ── URL helpers ───────────────────────────────────────────────────────────────

def referral_url(url: str) -> str:
    """Append referral tracking parameters to a URL."""
    if not url:
        return url
    if _REF_PARAM in url:
        return url
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["rid"] = [REFERRAL_ID]
    new_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def rewrite_links(text: str) -> str:
    """Rewrite every bare URL in text to include referral params."""
    if not text:
        return text
    urls = re.findall(r"https?://[^\s\)\]\"']+", text)
    for url in urls:
        text = text.replace(url, referral_url(url))
    return text


def search_url(query: str) -> str:
    """Build an Elimu Library search URL for a free-text query."""
    return f"{_ELIMU_SEARCH_BASE}{quote(query)}&{_REF_PARAM}&{_RETURN_PARAM}"
