"""
smoke_test.py — Quick smoke tests for scheduler, health, http_client, and service.
Run with: py smoke_test.py
"""
import sys
import time
sys.path.insert(0, "C:/Users/Lootus/MyAgent")

OK   = "\033[92mOK\033[0m"
FAIL = "\033[91mFAIL\033[0m"
passed = 0
failed = 0

def check(label, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  {OK}  {label}")
        passed += 1
    else:
        print(f"  {FAIL}  {label}" + (f": {detail}" if detail else ""))
        failed += 1

# ── Scheduler ─────────────────────────────────────────────────────────────────
print("=== Scheduler ===")
from elimu_ai.scheduler import (
    start_scheduler, shutdown_scheduler, get_status, run_all_tasks,
    _TASK_REGISTRY,
)

check("task registry has 5 tasks", len(_TASK_REGISTRY) == 5)

sched = start_scheduler(daemon=True)
time.sleep(0.5)
st = get_status()
check("scheduler.running == True",  st["running"] is True)
check("scheduler.started_at set",   st["started_at"] is not None)

shutdown_scheduler(wait=False)
time.sleep(0.3)
st2 = get_status()
check("scheduler.running == False after shutdown", st2["running"] is False)

# run_all_tasks returns dict with 5 keys
results = run_all_tasks()
check("run_all_tasks returns 5 results", len(results) == 5)
for name in ["answer_unanswered", "generate_discussions", "recommend_resources",
             "moderate_content", "catalog_sync"]:
    check(f"  task {name} ran", name in results)

# ── Health ─────────────────────────────────────────────────────────────────────
print()
print("=== Health ===")
from elimu_ai.health import get_health
h = get_health()
check("get_health returns dict",    isinstance(h, dict))
check("status key present",         "status" in h)
check("status is ok or degraded",   h["status"] in ("ok", "degraded"))
check("gemini key present",         "gemini" in h)
check("qdrant key present",         "qdrant" in h)
check("catalog key present",        "catalog" in h)

# ── HTTP client ────────────────────────────────────────────────────────────────
print()
print("=== HTTP Client ===")
from elimu_ai.http_client import ElimuAPIClient, get_client
from elimu_ai.config import AI_SHARED_SECRET, ELIMU_API_BASE_URL
from elimu_ai.exceptions import (
    ElimuAIError, HTTPClientError, AuthenticationError, HTTPResponseError
)

c = ElimuAPIClient()
check("client instantiates",         c is not None)
check("has .get method",              callable(getattr(c, "get", None)))
check("has .post method",             callable(getattr(c, "post", None)))
check("has .chat method",             callable(getattr(c, "chat", None)))
check("has .api_health method",       callable(getattr(c, "api_health", None)))
check("has .submit_task method",      callable(getattr(c, "submit_task", None)))
check("has .get_task_result method",  callable(getattr(c, "get_task_result", None)))
check("AI_SHARED_SECRET is str",      isinstance(AI_SHARED_SECRET, str))
check("ELIMU_API_BASE_URL is str",    isinstance(ELIMU_API_BASE_URL, str))
check("get_client() returns singleton", get_client() is get_client())

# Post without base_url set raises HTTPClientError (not crash)
c2 = ElimuAPIClient(base_url="")
try:
    c2.post("/api/ai/chat/", {"message": "hello"})
    check("empty base_url raises error", False, "should have raised")
except HTTPClientError:
    check("empty base_url raises HTTPClientError", True)
except Exception as e:
    check("empty base_url raises error", False, str(e))

# HTTPResponseError carries status_code
err = HTTPResponseError("not found", status_code=404)
check("HTTPResponseError.status_code", err.status_code == 404)

# ── Exceptions hierarchy ───────────────────────────────────────────────────────
print()
print("=== Exceptions ===")
from elimu_ai.exceptions import (
    GeminiUnavailableError, QdrantUnavailableError, CatalogError,
    SchedulerError, ConfigurationError, AgentError,
)
check("GeminiUnavailableError isa ElimuAIError",  issubclass(GeminiUnavailableError, ElimuAIError))
check("QdrantUnavailableError isa ElimuAIError",  issubclass(QdrantUnavailableError, ElimuAIError))
check("AuthenticationError isa HTTPClientError",  issubclass(AuthenticationError, HTTPClientError))
check("SchedulerError isa ElimuAIError",          issubclass(SchedulerError, ElimuAIError))
check("ConfigurationError isa ElimuAIError",      issubclass(ConfigurationError, ElimuAIError))

# ── Logging config ─────────────────────────────────────────────────────────────
print()
print("=== Logging config ===")
import logging
from elimu_ai.logging_config import configure_logging
configure_logging("DEBUG")
configure_logging("INFO")
check("configure_logging callable",   True)  # no exception = pass
root_level = logging.getLogger().level
check("root logger level set",        root_level > 0)

# ── Summary ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print()
    print("=" * 50)
    total = passed + failed
    if failed == 0:
        print(f"\033[92m  ALL {total} SMOKE TESTS PASSED\033[0m")
    else:
        print(f"\033[91m  {failed}/{total} SMOKE TESTS FAILED\033[0m")
    print("=" * 50)
    sys.exit(1 if failed else 0)
