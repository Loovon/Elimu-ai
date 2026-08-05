"""Tests for the Tool Registry."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from elimu_ai.tool_registry import registry, ToolDefinition, ToolRegistry


def test_registry_has_expected_tools():
    names = registry.all_names()
    for expected in ("teacher", "quiz", "librarian", "recommendation", "community", "catalog", "moderation"):
        assert expected in names, f"Missing tool: {expected}"


def test_tools_for_quiz_intent():
    tools = registry.tools_for_intents(["quiz"])
    names = [t.name for t in tools]
    assert "quiz" in names


def test_tools_for_librarian_intent():
    tools = registry.tools_for_intents(["librarian"])
    names = [t.name for t in tools]
    assert "librarian" in names or "recommendation" in names


def test_tools_sorted_by_priority():
    tools = registry.tools_for_intents(["teacher", "quiz", "librarian"])
    for i in range(len(tools) - 1):
        assert tools[i].priority >= tools[i + 1].priority


def test_multi_intent_returns_multiple_tools():
    tools = registry.tools_for_intents(["quiz", "recommendation"])
    names = [t.name for t in tools]
    assert "quiz" in names
    assert len(tools) >= 2


def test_execution_plan_no_duplicates():
    plan = registry.execution_plan(["teacher", "quiz"])
    names = [t.name for t in plan]
    assert len(names) == len(set(names)), "Duplicate tools in execution plan"


def test_execution_plan_respects_dependencies():
    # Build a mini registry with a dependency
    reg = ToolRegistry()
    reg.register(ToolDefinition(
        name="base",
        description="Base tool",
        supported_intents={"base_intent"},
        priority=50,
        required_resources=set(),
        dependencies=[],
        execute=lambda context, question, **_: "base result",
    ))
    reg.register(ToolDefinition(
        name="derived",
        description="Derived tool that depends on base",
        supported_intents={"derived_intent"},
        priority=60,
        required_resources=set(),
        dependencies=["base"],
        execute=lambda context, question, **_: "derived result",
    ))
    plan = reg.execution_plan(["derived_intent"])
    names = [t.name for t in plan]
    assert names.index("base") < names.index("derived")


def test_moderation_has_highest_priority():
    tools = registry.tools_for_intents(["moderation"])
    assert tools[0].name == "moderation"
    assert tools[0].priority >= 90


def test_exclude_resources_filters_tools():
    # Exclude gemini — teacher tool requires it
    tools = registry.tools_for_intents(["teacher"], exclude_resources={"gemini"})
    names = [t.name for t in tools]
    assert "teacher" not in names


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
