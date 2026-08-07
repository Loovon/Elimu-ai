"""
elimu_ai/agents/query_parser.py

Compatibility shim — the canonical QueryParser lives in elimu_ai.query_parser.
This module re-exports it so that imports from either location work.

Canonical import (preferred):
    from elimu_ai.query_parser import QueryParser, query_parser, ParsedQuery

Legacy / agent-package import (also works):
    from elimu_ai.agents.query_parser import QueryParser
"""
from elimu_ai.query_parser import QueryParser, query_parser, ParsedQuery  # noqa: F401

__all__ = ["QueryParser", "query_parser", "ParsedQuery"]
