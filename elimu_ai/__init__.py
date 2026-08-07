"""
elimu_ai — Autonomous educational AI platform for Kenyan learners.

Architecture:
  API          service.py          FastAPI HTTP layer
  Agent        agent.py            Backward-compatible entry point
  Supervisor   agents/supervisor.py Multi-agent pipeline coordinator
  Intent       agents/intent_agent.py Semantic multi-intent detection
  Planner      agents/planner.py   Execution plan generation
  Tool Sel.    agents/tool_selector.py Dynamic tool resolution
  Verifier     agents/verifier.py  Output quality verification
  Learning     agents/learning.py  Failure recording + routing improvement
  Orchestrator orchestrator.py     Fallback execution engine
  Scheduler    scheduler.py        APScheduler background tasks
  Memory       memory.py           Session + long-term memory
  DB           db/                 PostgreSQL repository layer
  Personas     personas/           Per-persona configuration
  NL Writer    natural_language.py Human-tone response writer
  Query Parser query_parser.py     Multi-query compound understanding
  Email        email_alerts.py     Failure notifications

Public surface:
  from elimu_ai.agent     import run_agent
  from elimu_ai.service   import app
  from elimu_ai.scheduler import start_scheduler, run_all_tasks
  from elimu_ai.agents    import SupervisorAgent
"""
