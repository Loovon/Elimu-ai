"""
test_agent.py

Master test runner — runs all elimu_ai test suites.

Usage:
    py test_agent.py

Discovers and runs every test_*.py file under elimu_ai/tests/.
Reports pass/fail counts and exits with code 1 on any failure.
"""
import sys
import pathlib
import importlib
import traceback

ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

GREEN = "\033[92m"
RED   = "\033[91m"
RESET = "\033[0m"

test_dir = ROOT / "elimu_ai" / "tests"
test_files = sorted(test_dir.glob("test_*.py"))

total_passed = 0
total_failed = 0
suite_errors = []

for test_file in test_files:
    module_name = f"elimu_ai.tests.{test_file.stem}"
    try:
        mod = importlib.import_module(module_name)
    except Exception as e:
        print(f"\n{RED}IMPORT ERROR{RESET} {test_file.name}: {e}")
        suite_errors.append((test_file.name, str(e)))
        continue

    tests = {k: v for k, v in vars(mod).items() if k.startswith("test_") and callable(v)}
    if not tests:
        continue

    suite_pass = suite_fail = 0
    print(f"\n{'─'*60}")
    print(f"  {test_file.stem}")
    print(f"{'─'*60}")

    for name, fn in tests.items():
        try:
            fn()
            print(f"  {GREEN}PASS{RESET}  {name}")
            suite_pass += 1
        except Exception:
            tb = traceback.format_exc(limit=3)
            print(f"  {RED}FAIL{RESET}  {name}")
            print(f"       {tb.strip().splitlines()[-1]}")
            suite_fail += 1

    total_passed += suite_pass
    total_failed += suite_fail
    status = f"{GREEN}{suite_pass} passed{RESET}" if not suite_fail else \
             f"{GREEN}{suite_pass} passed{RESET}, {RED}{suite_fail} failed{RESET}"
    print(f"  → {status}")

print(f"\n{'='*60}")
total = total_passed + total_failed
if total_failed == 0 and not suite_errors:
    print(f"{GREEN}  ALL {total} TESTS PASSED{RESET}")
else:
    print(f"{GREEN}  {total_passed}/{total} PASSED{RESET}  {RED}{total_failed} FAILED{RESET}")
    if suite_errors:
        print(f"{RED}  {len(suite_errors)} SUITE IMPORT ERROR(S){RESET}")
        for name, err in suite_errors:
            print(f"    {name}: {err}")
print(f"{'='*60}")

sys.exit(1 if (total_failed or suite_errors) else 0)
