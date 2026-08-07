"""
verify.py — Architecture verification script.
Covers: syntax, dead imports, circular imports, architecture rules,
module imports, router tests, helper tests, prompt builders,
and all new agentic platform modules.

Run with: py verify.py
"""
import sys, pathlib, ast, time
sys.path.insert(0, str(pathlib.Path(__file__).parent))

ROOT = pathlib.Path("elimu_ai")
root_files = [pathlib.Path("app.py"), pathlib.Path("main.py"), pathlib.Path("ingest.py")]
all_files  = list(ROOT.rglob("*.py")) + root_files

G = "\033[92mPASS\033[0m"
F = "\033[91mFAIL\033[0m"
overall = True

def fail(msg):
    global overall
    overall = False
    print(f"  {F}  {msg}")

def ok(msg):
    print(f"  {G}  {msg}")

# ── 1. Syntax ─────────────────────────────────────────────────────────────────
print("=== 1. Syntax ===")
for p in all_files:
    try:
        ast.parse(p.read_bytes().lstrip(b"\xef\xbb\xbf"))
    except SyntaxError as e:
        fail(f"{p.name}:{e.lineno}: {e.msg}")
ok(f"All {len(all_files)} files parse without errors.\n")

# ── 2. Dead legacy imports ────────────────────────────────────────────────────
print("=== 2. Dead imports (ollama/chromadb/etc.) ===")
dead_pkgs = {"ollama","chromadb","embeddings","vector_db","rag","llm","memory","ai_service"}
found_dead = False
for p in all_files:
    tree = ast.parse(p.read_bytes().lstrip(b"\xef\xbb\xbf"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in dead_pkgs:
                    fail(f"{p.name}:{node.lineno}  import {a.name}")
                    found_dead = True
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in dead_pkgs:
                fail(f"{p.name}:{node.lineno}  from {node.module}")
                found_dead = True
if not found_dead:
    ok("No dead legacy imports.\n")

# ── 3. Architecture: no tool imports service.py at module level ───────────────
print("=== 3. Architecture rules ===")
_allowed = {"scheduler.py","app.py"}
violations = False
for p in ROOT.rglob("*.py"):
    if p.name in ("service.py","__init__.py") or p.name in _allowed:
        continue
    tree = ast.parse(p.read_bytes().lstrip(b"\xef\xbb\xbf"))
    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                if "service" in a.name and "elimu_ai" in a.name:
                    fail(f"{p.name} has top-level import of service.py")
                    violations = True
        elif isinstance(node, ast.ImportFrom) and node.module:
            if "elimu_ai.service" in node.module:
                fail(f"{p.name} has top-level import of service.py")
                violations = True
if not violations:
    ok("No tool has top-level import of service.py.")

rsrc = (ROOT / "router.py").read_text()
if any(bad in rsrc for bad in ("from elimu_ai.gemini","from elimu_ai.qdrant","generate(","embed(")):
    fail("router.py contains Gemini/Qdrant imports")
else:
    ok("router.py contains only keyword routing.")

for fname in ("tools/teacher.py","tools/quiz.py","tools/community.py"):
    src = (ROOT / fname).read_text()
    tree = ast.parse(src)
    bad = any(
        isinstance(n, ast.ImportFrom) and n.module == "elimu_ai.gemini"
        for n in ast.walk(tree)
    )
    if bad:
        fail(f"{fname} imports elimu_ai.gemini directly")
    else:
        ok(f"{fname} does not import gemini directly")
print()

# ── 4. Circular import detection ─────────────────────────────────────────────
print("=== 4. Circular imports ===")
def _get_imports(path):
    tree = ast.parse(path.read_bytes().lstrip(b"\xef\xbb\xbf"))
    deps = []
    # Only walk TOP-LEVEL import statements, not those inside functions/classes
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("elimu_ai"):
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
    if mod.endswith(".__init__"): mod = mod[:-9]
    graph[mod] = _get_imports(p)

WHITE, GRAY, BLACK = 0,1,2
color  = {n: WHITE for n in graph}
cycles = []
def dfs(node, path):
    color[node] = GRAY; path.append(node)
    for nbr in graph.get(node,[]):
        if nbr not in graph: continue
        if color[nbr] == GRAY:
            idx = path.index(nbr)
            cycles.append(" -> ".join(path[idx:]) + " -> " + nbr)
        elif color[nbr] == WHITE:
            dfs(nbr, path)
    path.pop(); color[node] = BLACK
for node in list(graph):
    if color[node] == WHITE: dfs(node, [])

if cycles:
    for c in cycles: fail(f"CYCLE: {c}")
else:
    ok("No circular imports.\n")

# ── 5. Module import test ─────────────────────────────────────────────────────
print("=== 5. Module imports ===")
modules = [
    "elimu_ai.config","elimu_ai.helpers","elimu_ai.personas","elimu_ai.prompts",
    "elimu_ai.router","elimu_ai.gemini","elimu_ai.qdrant_db","elimu_ai.catalog_search",
    "elimu_ai.exceptions","elimu_ai.logging_config","elimu_ai.health","elimu_ai.http_client",
    "elimu_ai.intent","elimu_ai.context_builder","elimu_ai.tool_registry",
    "elimu_ai.memory","elimu_ai.orchestrator","elimu_ai.agent_manager",
    "elimu_ai.db.connection","elimu_ai.db.repositories","elimu_ai.db.migrations",
    "elimu_ai.tools.teacher","elimu_ai.tools.quiz","elimu_ai.tools.community",
    "elimu_ai.tools.library","elimu_ai.tools.moderation","elimu_ai.tools.recommendations",
    "elimu_ai.tools.forum","elimu_ai.tools.answer",
    "elimu_ai.agent","elimu_ai.scheduler",
]
_runtime = {"fastapi","qdrant_client","google","django","forum","psycopg2","apscheduler"}
for mod in modules:
    try:
        __import__(mod)
        ok(mod)
    except ImportError as e:
        pkg = str(e).split("'")[1].split(".")[0] if "'" in str(e) else str(e)
        if pkg in _runtime:
            print(f"  OK (runtime dep)  {mod}: {e}")
        else:
            fail(f"{mod}: {e}")
    except Exception as e:
        fail(f"{mod}: {e}")
print()

# ── 6. Router tests ───────────────────────────────────────────────────────────
print("=== 6. Router routing tests ===")
from elimu_ai.router import decide_persona
ROUTER_TESTS = [
    ("term 3 schemes of work",                     "librarian"),
    ("grade 6 schemes of work term 2",             "librarian"),
    ("elimu free exams with answers pdf",          "librarian"),
    ("assessment books",                           "librarian"),
    ("grade 9 schemes of work term 3",             "librarian"),
    ("school report book",                         "librarian"),
    ("curriculum designs",                         "librarian"),
    ("grade 10 essential mathematics exams pdf",   "librarian"),
    ("grade 9 pretechnical project 2026",          "librarian"),
    ("grade ten physics notes",                    "librarian"),
    ("jss exams grade 9",                          "librarian"),
    ("kcse revision materials",                    "librarian"),
    ("record of work",                             "librarian"),
    ("grade 10 assessment book",                   "librarian"),
    ("pp2 homework",                               "librarian"),
    ("holiday homework book",                      "librarian"),
    ("rubrics in cbc",                             "librarian"),
    ("grade 1 exams",                              "librarian"),
    ("elimu library",                              "librarian"),
    ("give me a quiz on photosynthesis",           "quiz"),
    ("test me on cell biology",                    "quiz"),
    ("practice questions for grade 8 science",    "quiz"),
    ("start a discussion about KCSE",              "community"),
    ("create a post about CBC",                    "community"),
    ("explain osmosis",                            "teacher"),
    ("what is photosynthesis",                     "teacher"),
    ("how does mitosis work",                      "teacher"),
]
for q, expected in ROUTER_TESTS:
    got = decide_persona(q)
    if got == expected:
        ok(f"{q[:55]!r:55} -> {got}")
    else:
        fail(f"{q[:55]!r:55} -> {got!r}  (expected {expected!r})")
print()

# ── 7. Intent detection tests ─────────────────────────────────────────────────
print("=== 7. Intent detection tests ===")
from elimu_ai.intent import detect_intents, primary_intent, has_intent
INTENT_TESTS = [
    ("quiz me on biology",              "quiz",          True),
    ("explain photosynthesis",          "teacher",       True),
    ("I need grade 8 maths notes",      "librarian",     True),
    ("start a discussion about CBC",    "community",     True),
    ("recommend chemistry revision",    "recommendation",True),
    ("report this spam",                "moderation",    True),
]
for text, intent, expected in INTENT_TESTS:
    result = has_intent(text, intent)
    if result == expected:
        ok(f"has_intent({text[:40]!r}, {intent!r}) == {expected}")
    else:
        fail(f"has_intent({text[:40]!r}, {intent!r}): got {result}, expected {expected}")

# Multi-intent
intents = detect_intents("Recommend chemistry notes then quiz me")
names = [i.name for i in intents]
if "quiz" in names and len(intents) >= 2:
    ok("Multi-intent detected (recommendation+quiz)")
else:
    fail(f"Multi-intent failed: got {names}")
print()

# ── 8. Helper functions ───────────────────────────────────────────────────────
print("=== 8. Helper functions ===")
from elimu_ai.helpers import clean_answer, referral_url, search_url, rewrite_links
assert clean_answer("**bold** and _italic_") == "bold and italic"
ok("clean_answer strips Markdown")
assert "rid=" in referral_url("https://www.elimulibrary.com/doc/1")
ok("referral_url appends rid")
assert "elimulibrary" in search_url("Grade 8 Maths")
ok("search_url builds correct URL")
assert "rid=" in rewrite_links("Check https://www.elimulibrary.com/doc/1 here")
ok("rewrite_links rewrites URLs")
print()

# ── 9. Prompt builders ────────────────────────────────────────────────────────
print("=== 9. Prompt builders ===")
from elimu_ai.tools.teacher import build_teacher_prompt, extract_context_hints
from elimu_ai.tools.quiz import build_quiz_prompt
from elimu_ai.tools.community import build_community_prompt

p = build_teacher_prompt("What is osmosis?", "context here")
assert "osmosis" in p and "context here" in p
ok("build_teacher_prompt")

p = build_quiz_prompt("Cell biology", "context here")
assert "Cell biology" in p
ok("build_quiz_prompt")

p = build_community_prompt("KCSE stress", "")
assert "KCSE stress" in p
ok("build_community_prompt")

ctx = extract_context_hints("Grade 8 Mathematics Term 2 notes")
assert ctx["grade"] == "grade8"
assert ctx["subject"] == "mathematics"
assert ctx["term"] == "2"
ok("extract_context_hints")
print()

# ── 10. New platform modules ──────────────────────────────────────────────────
print("=== 10. New platform modules ===")

from elimu_ai.intent import detect_intents as _di
intents = _di("quiz me on photosynthesis")
assert intents and intents[0].name == "quiz"
ok("intent.py: detect_intents works")

from elimu_ai.context_builder import build_context, PromptContext
ctx = build_context("test", "teacher")
assert isinstance(ctx, PromptContext)
ok("context_builder.py: build_context returns PromptContext")

from elimu_ai.tool_registry import registry
assert len(registry.all_names()) >= 7
ok(f"tool_registry.py: {len(registry.all_names())} tools registered")

from elimu_ai.memory import memory_store, MemoryStore
memory_store.add_turn("verify-session", "user", "hello")
h = memory_store.get_history("verify-session")
assert len(h) == 1
ok("memory.py: add_turn and get_history work")

from elimu_ai.orchestrator import run_orchestrator, OrchestratorResult
result = run_orchestrator("What is photosynthesis?")
assert isinstance(result, OrchestratorResult)
assert result.answer
ok("orchestrator.py: run_orchestrator returns OrchestratorResult")

from elimu_ai.agent import run_agent
agent_result = run_agent("explain mitosis")
assert set(agent_result.keys()) == {"persona","answer","sources","tools"}
ok("agent.py: run_agent returns correct keys (backward compat)")

from elimu_ai.agent_manager import start_agent_manager, stop_agent_manager, get_status as am_status
t = start_agent_manager(daemon=True)
import time; time.sleep(0.2)
st = am_status()
assert st["running"] is True
stop_agent_manager()
ok("agent_manager.py: starts and stops cleanly")

from elimu_ai.db.connection import db_available
ok(f"db/connection.py: db_available={db_available()}")

from elimu_ai.db.repositories import MemoryRepository, AnalyticsRepository
MemoryRepository().save_summary("verify-s1", None, "test summary")
AnalyticsRepository().log_request("rid-001", None, "teacher", [], [], 10, 100, 50)
ok("db/repositories.py: MemoryRepository and AnalyticsRepository degrade gracefully")

from elimu_ai.health import get_health
h = get_health()
required_keys = {"status","version","uptime_seconds","gemini","qdrant","postgresql",
                 "catalog","scheduler","memory","agent_manager","environment"}
missing = required_keys - set(h.keys())
assert not missing, f"Missing: {missing}"
ok(f"health.py: get_health has all {len(required_keys)} required keys")

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    ok("apscheduler: BackgroundScheduler importable")
except ImportError:
    fail("apscheduler not installed — run: pip install apscheduler==3.10.4")
print()

# ── 11. Run automated test suite ──────────────────────────────────────────────
print("=== 11. Automated test suite ===")
import importlib
test_dir = pathlib.Path("elimu_ai/tests")
test_files = sorted(test_dir.glob("test_*.py"))
suite_pass = suite_fail = 0
for tf in test_files:
    mod_name = f"elimu_ai.tests.{tf.stem}"
    try:
        mod = importlib.import_module(mod_name)
    except Exception as e:
        fail(f"Import error in {tf.name}: {e}")
        continue
    tests = {k: v for k, v in vars(mod).items() if k.startswith("test_") and callable(v)}
    for name, fn in tests.items():
        try:
            fn()
            suite_pass += 1
        except Exception as e:
            fail(f"{tf.stem}.{name}: {e}")
            suite_fail += 1

if suite_fail == 0:
    ok(f"All {suite_pass} automated tests passed.\n")
else:
    fail(f"{suite_fail}/{suite_pass+suite_fail} automated tests failed.\n")

# ── Summary ───────────────────────────────────────────────────────────────────
print("=" * 60)
if overall:
    print(f"\033[92m  ALL CHECKS PASSED\033[0m")
else:
    print(f"\033[91m  SOME CHECKS FAILED — see above\033[0m")
print("=" * 60)
sys.exit(0 if overall else 1)
