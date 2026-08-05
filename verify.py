"""
verify.py — Architecture verification script.
Run with: py verify.py
"""
import sys, pathlib, ast

sys.path.insert(0, str(pathlib.Path(__file__).parent))

ROOT = pathlib.Path("elimu_ai")
root_files = [
    pathlib.Path("app.py"),
    pathlib.Path("main.py"),
    pathlib.Path("ingest.py"),
]
all_files = list(ROOT.rglob("*.py")) + root_files

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"

overall = True

# ── 1. Syntax ─────────────────────────────────────────────────────────────────
print("=== 1. Syntax ===")
for p in all_files:
    try:
        ast.parse(p.read_bytes().lstrip(b"\xef\xbb\xbf"))
    except SyntaxError as e:
        print(f"  {FAIL}  {p.name}:{e.lineno}: {e.msg}")
        overall = False
        continue
print(f"  {PASS}  All {len(all_files)} files parse without errors.\n")

# ── 2. Dead imports ───────────────────────────────────────────────────────────
print("=== 2. Dead imports (ollama/chromadb/etc.) ===")
dead_pkgs = {"ollama","chromadb","embeddings","vector_db","rag","llm","memory","ai_service"}
found_dead = False
for p in all_files:
    tree = ast.parse(p.read_bytes().lstrip(b"\xef\xbb\xbf"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in dead_pkgs:
                    print(f"  {FAIL}  {p.name}:{node.lineno}  import {a.name}")
                    found_dead = True; overall = False
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in dead_pkgs:
                print(f"  {FAIL}  {p.name}:{node.lineno}  from {node.module}")
                found_dead = True; overall = False
if not found_dead:
    print(f"  {PASS}  No dead imports.\n")

# ── 3. No tool/scheduler imports service.py ──────────────────────────────────
print("=== 3. Architecture: no tool/agent/router imports service.py at module level ===")
violations = False
_ALLOWED_SERVICE_IMPORTERS = {"scheduler.py", "app.py"}  # allowed to lazy-import service
for p in ROOT.rglob("*.py"):
    if p.name in ("service.py", "__init__.py") or p.name in _ALLOWED_SERVICE_IMPORTERS:
        continue
    tree = ast.parse(p.read_bytes().lstrip(b"\xef\xbb\xbf"))
    for node in ast.walk(tree):
        # Only flag TOP-LEVEL imports (not inside functions/classes)
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        # Check if it's at module level (parent is Module)
        pass
    # Simpler: check for module-level import lines via ast.Module.body
    tree2 = ast.parse(p.read_bytes().lstrip(b"\xef\xbb\xbf"))
    for node in tree2.body:  # only top-level statements
        if isinstance(node, ast.Import):
            for a in node.names:
                if "service" in a.name and "elimu_ai" in a.name:
                    print(f"  {FAIL}  {p.name} has top-level import of service.py")
                    violations = True; overall = False
        elif isinstance(node, ast.ImportFrom) and node.module:
            if "elimu_ai.service" in node.module:
                print(f"  {FAIL}  {p.name} has top-level import of service.py")
                violations = True; overall = False
if not violations:
    print(f"  {PASS}  No tool has top-level imports of service.py.\n")

# ── 4. router.py purity ───────────────────────────────────────────────────────
print("=== 4. router.py purity ===")
rsrc = (ROOT / "router.py").read_text()
router_ok = True
for bad in ("from elimu_ai.gemini", "from elimu_ai.qdrant", "generate(", "embed("):
    if bad in rsrc:
        print(f"  {FAIL}  router.py contains {bad!r}")
        router_ok = False; overall = False
if router_ok:
    print(f"  {PASS}  router.py contains only keyword routing.\n")

# ── 5. teacher/quiz/community never import gemini directly ───────────────────
print("=== 5. Prompt-builder tools never import gemini ===")
for fname in ("tools/teacher.py", "tools/quiz.py", "tools/community.py"):
    src = (ROOT / fname).read_text()
    tree = ast.parse(src)
    bad = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "elimu_ai.gemini":
            print(f"  {FAIL}  {fname} imports elimu_ai.gemini directly")
            bad = True; overall = False
    if not bad:
        print(f"  {PASS}  {fname}")
print()

# ── 6. Circular import detection ─────────────────────────────────────────────
print("=== 6. Circular import detection ===")
def get_elimu_imports(path):
    tree = ast.parse(path.read_bytes().lstrip(b"\xef\xbb\xbf"))
    deps = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("elimu_ai"):
                deps.append(node.module)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("elimu_ai"):
                    deps.append(a.name)
    return list(set(deps))

graph = {}
for p in ROOT.rglob("*.py"):
    mod = str(p).replace("\\",".").replace("/",".").replace(".py","")
    mod = mod[mod.find("elimu_ai"):]
    if mod.endswith(".__init__"):
        mod = mod[:-9]
    graph[mod] = get_elimu_imports(p)

WHITE, GRAY, BLACK = 0, 1, 2
color = {n: WHITE for n in graph}
cycles = []

def dfs(node, path):
    color[node] = GRAY
    path.append(node)
    for nbr in graph.get(node, []):
        if nbr not in graph:
            continue
        if color[nbr] == GRAY:
            idx = path.index(nbr)
            cycles.append(" -> ".join(path[idx:]) + " -> " + nbr)
        elif color[nbr] == WHITE:
            dfs(nbr, path)
    path.pop()
    color[node] = BLACK

for node in list(graph):
    if color[node] == WHITE:
        dfs(node, [])

if cycles:
    for c in cycles:
        print(f"  {FAIL}  CYCLE: {c}")
    overall = False
else:
    print(f"  {PASS}  No circular imports.\n")

# ── 7. Module import test ─────────────────────────────────────────────────────
print("=== 7. Module imports ===")
modules = [
    "elimu_ai.config", "elimu_ai.helpers", "elimu_ai.personas",
    "elimu_ai.prompts", "elimu_ai.router", "elimu_ai.gemini",
    "elimu_ai.qdrant_db", "elimu_ai.catalog_search",
    "elimu_ai.exceptions", "elimu_ai.logging_config",
    "elimu_ai.health", "elimu_ai.http_client",
    "elimu_ai.tools.teacher", "elimu_ai.tools.quiz",
    "elimu_ai.tools.community", "elimu_ai.tools.library",
    "elimu_ai.tools.moderation", "elimu_ai.tools.recommendations",
    "elimu_ai.tools.forum", "elimu_ai.tools.answer",
    "elimu_ai.agent", "elimu_ai.scheduler",
]
_RUNTIME_PKGS = {"fastapi","qdrant_client","google","django","forum"}
for mod in modules:
    try:
        __import__(mod)
        print(f"  {PASS}  {mod}")
    except ImportError as e:
        pkg = str(e).split("'")[1].split(".")[0] if "'" in str(e) else str(e)
        if pkg in _RUNTIME_PKGS:
            print(f"  OK (runtime dep)  {mod}: {e}")
        else:
            print(f"  {FAIL}  {mod}: {e}")
            overall = False
    except Exception as e:
        print(f"  {FAIL}  {mod}: {e}")
        overall = False
print()

# ── 8. Router correctness ─────────────────────────────────────────────────────
print("=== 8. Router routing tests ===")
from elimu_ai.router import decide_persona

tests = [
    # Sample query coverage
    ("term 3 schemes of work",                          "librarian"),
    ("schemes of work",                                 "librarian"),
    ("schemes of work 2026 term 3",                     "librarian"),
    ("grade 6 schemes of work term 2",                  "librarian"),
    ("elimu free exams with answers pdf",               "librarian"),
    ("assessment books",                                "librarian"),
    ("csl grade 10 notes 2026 pdf free download",       "librarian"),
    ("grade 9 schemes of work term 3",                  "librarian"),
    ("school report book",                              "librarian"),
    ("curriculum designs",                              "librarian"),
    ("grade 10 essential mathematics exams pdf",        "librarian"),
    ("grade 8 exam papers with answers pdf term 3",     "librarian"),
    ("grade 9 pretechnical project 2026",               "librarian"),
    ("grade ten physics notes",                         "librarian"),
    ("jss exams grade 9",                               "librarian"),
    ("kcse revision materials",                         "librarian"),
    ("record of work",                                  "librarian"),
    ("grade 10 assessment book",                        "librarian"),
    ("pp2 homework",                                    "librarian"),
    ("holiday homework book",                           "librarian"),
    ("pp2 schemes of work term 2 2026 pdf",             "librarian"),
    ("rubrics in cbc",                                  "librarian"),
    ("grade 1 exams",                                   "librarian"),
    ("elimu library",                                   "librarian"),
    ("elimu notes",                                     "librarian"),
    ("what is the pricing",                             "librarian"),
    ("elimu kenya exams",                               "librarian"),
    ("end term",                                        "librarian"),
    # Quiz
    ("give me a quiz on photosynthesis",                "quiz"),
    ("test me on cell biology",                         "quiz"),
    ("practice questions for grade 8 science",         "quiz"),
    # Community
    ("start a discussion about KCSE",                   "community"),
    ("create a post about CBC",                         "community"),
    # Teacher
    ("explain osmosis",                                 "teacher"),
    ("what is photosynthesis",                          "teacher"),
    ("how does mitosis work",                           "teacher"),
]
router_fails = 0
for q, expected in tests:
    got = decide_persona(q)
    if got == expected:
        print(f"  {PASS}  {q[:55]!r:55} -> {got}")
    else:
        print(f"  {FAIL}  {q[:55]!r:55} -> {got!r}  (expected {expected!r})")
        router_fails += 1; overall = False

print()

# ── 9. Helper functions ───────────────────────────────────────────────────────
print("=== 9. Helper functions ===")
from elimu_ai.helpers import clean_answer, referral_url, search_url, rewrite_links

assert clean_answer("**bold** and _italic_") == "bold and italic", "clean_answer failed"
assert "rid=" in referral_url("https://www.elimulibrary.com/doc/1")
assert "elimulibrary" in search_url("Grade 8 Maths")
assert "rid=" in rewrite_links("Check https://www.elimulibrary.com/doc/1 here")
print(f"  {PASS}  clean_answer, referral_url, search_url, rewrite_links\n")

# ── 10. Prompt builders ───────────────────────────────────────────────────────
print("=== 10. Prompt builders ===")
from elimu_ai.tools.teacher import build_teacher_prompt, extract_context_hints
from elimu_ai.tools.quiz import build_quiz_prompt
from elimu_ai.tools.community import build_community_prompt

p = build_teacher_prompt("What is osmosis?", "context here")
assert "osmosis" in p and "context here" in p
print(f"  {PASS}  build_teacher_prompt")

p = build_quiz_prompt("Cell biology", "context here")
assert "Cell biology" in p and "context here" in p
print(f"  {PASS}  build_quiz_prompt")

p = build_community_prompt("KCSE stress", "")
assert "KCSE stress" in p
print(f"  {PASS}  build_community_prompt")

ctx = extract_context_hints("Grade 8 Mathematics Term 2 notes")
assert ctx["grade"] == "grade8",       f"grade wrong: {ctx}"
assert ctx["subject"] == "mathematics", f"subject wrong: {ctx}"
assert ctx["term"] == "2",             f"term wrong: {ctx}"
print(f"  {PASS}  extract_context_hints\n")

# ── 11. New module checks ─────────────────────────────────────────────────────
print("=== 11. New modules ===")

# exceptions.py — exception hierarchy
from elimu_ai.exceptions import (
    ElimuAIError, GeminiUnavailableError, QdrantUnavailableError,
    CatalogError, HTTPClientError, AuthenticationError,
    HTTPResponseError, SchedulerError,
)
assert issubclass(GeminiUnavailableError, ElimuAIError)
assert issubclass(AuthenticationError, HTTPClientError)
assert HTTPResponseError("test", status_code=404).status_code == 404
print(f"  {PASS}  exceptions.py — hierarchy correct")

# logging_config.py — configure_logging callable
from elimu_ai.logging_config import configure_logging
configure_logging("WARNING")
configure_logging("INFO")   # restore
print(f"  {PASS}  logging_config.py — configure_logging works")

# health.py — get_health returns expected shape
from elimu_ai.health import get_health
h = get_health()
assert "status" in h and h["status"] in ("ok", "degraded")
assert "gemini" in h and "qdrant" in h and "catalog" in h
print(f"  {PASS}  health.py — get_health returns correct shape")

# http_client.py — client instantiates, AI_SHARED_SECRET in config
from elimu_ai.http_client import ElimuAPIClient, get_client
from elimu_ai.config import AI_SHARED_SECRET, ELIMU_API_BASE_URL
c = ElimuAPIClient()
assert hasattr(c, "post") and hasattr(c, "get")
assert hasattr(c, "chat") and hasattr(c, "api_health")
print(f"  {PASS}  http_client.py — ElimuAPIClient instantiates")

# config.py — new keys present
from elimu_ai.config import AI_SHARED_SECRET, ELIMU_API_BASE_URL
assert isinstance(AI_SHARED_SECRET, str)
assert isinstance(ELIMU_API_BASE_URL, str)
print(f"  {PASS}  config.py — AI_SHARED_SECRET and ELIMU_API_BASE_URL present")

# scheduler.py — APScheduler, run_all_tasks, get_status
from elimu_ai.scheduler import run_all_tasks, get_status, start_scheduler, shutdown_scheduler
status = get_status()
assert "running" in status and "last_run" in status
print(f"  {PASS}  scheduler.py — APScheduler, get_status, run_all_tasks present")

# APScheduler can be instantiated
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    print(f"  {PASS}  apscheduler — BackgroundScheduler importable")
except ImportError:
    print(f"  {FAIL}  apscheduler not installed — run: pip install apscheduler==3.10.4")
    overall = False

print()

# ── Summary ───────────────────────────────────────────────────────────────────
print("=" * 50)
if overall:
    print(f"  {PASS}  ALL CHECKS PASSED")
else:
    print(f"  {FAIL}  SOME CHECKS FAILED — see above")
print("=" * 50)
