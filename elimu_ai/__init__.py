"""
elimu_ai

Autonomous educational AI platform for Kenyan learners.
Powers ElimuTalks forum and the Elimu Library.

Architecture layers
-------------------
API layer        : service.py      (FastAPI endpoints)
Orchestrator     : orchestrator.py (multi-tool execution planner)
Intent detection : intent.py       (confidence-scored multi-intent)
Tool registry    : tool_registry.py(declarative tool catalogue)
Context builder  : context_builder.py (assembles Gemini prompt context)
Memory           : memory.py       (session + long-term memory)
DB repositories  : db/repositories.py (PostgreSQL access layer)
Agent manager    : agent_manager.py (continuous background observer)
Scheduler        : scheduler.py    (APScheduler background jobs)

Public surface
--------------
  from elimu_ai.agent        import run_agent
  from elimu_ai.service      import app           # FastAPI ASGI app
  from elimu_ai.orchestrator import run_orchestrator
  from elimu_ai.scheduler    import start_scheduler, run_all_tasks
  from elimu_ai.agent_manager import start_agent_manager
  from elimu_ai.memory       import memory_store
  from elimu_ai.intent       import detect_intents
"""
