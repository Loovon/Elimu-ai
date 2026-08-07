"""
elimu_ai/agents/ — Multi-agent framework.

Agents:
  SupervisorAgent   — plans, delegates, verifies, retries, approves
  IntentAgent       — semantic multi-intent detection via Gemini
  PlannerAgent      — generates step-by-step execution plans
  ToolSelectorAgent — chooses tools without hardcoding
  VerifierAgent     — verifies output quality before returning
  LearningAgent     — records failures and improves routing over time
"""
from elimu_ai.agents.supervisor import SupervisorAgent
from elimu_ai.agents.intent_agent import IntentAgent
from elimu_ai.agents.planner import PlannerAgent
from elimu_ai.agents.tool_selector import ToolSelectorAgent
from elimu_ai.agents.verifier import VerifierAgent
from elimu_ai.agents.learning import LearningAgent

__all__ = [
    "SupervisorAgent",
    "IntentAgent",
    "PlannerAgent",
    "ToolSelectorAgent",
    "VerifierAgent",
    "LearningAgent",
]
