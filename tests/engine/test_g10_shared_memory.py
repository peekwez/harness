"""G10: an agent write into .claude/memory/shared/ is blocked (#6)."""
import pytest

from conftest import make_event
from engine.events import handle_event


def _g10(verdict):
    return [f for f in verdict["findings"] if f["code"] == "SHARED_MEMORY_WRITE"]


@pytest.mark.parametrize("rel", [
    ".claude/memory/shared/MEMORY.md",
    ".claude/memory/shared/new-fact.md",
    ".claude/memory/shared",
    "./.claude/memory/shared/x.md",
    ".claude\\memory\\shared\\x.md",
    ".Claude/Memory/Shared/x.md",
    "docs/../.claude/memory/shared/x.md",
])
def test_agent_write_into_shared_memory_is_blocked(toy, rel):
    v = handle_event(make_event("pre_change", session="g10", files=[rel]), toy)
    assert v["verdict"] == "block"
    [finding] = _g10(v)
    assert finding["rule_ref"] == "gate:G10"
    assert finding["severity"] == "block"
    assert "harness memory promote" in finding["message"]
    assert len(finding["message"].split("Fix:")[0].split()) <= 25


def test_absolute_path_is_blocked(toy):
    path = str(toy / ".claude" / "memory" / "shared" / "x.md")
    v = handle_event(make_event("pre_change", session="g10", files=[path]), toy)
    assert v["verdict"] == "block" and _g10(v)


def test_block_needs_no_bound_slice(toy):
    v = handle_event(make_event("pre_change", session="g10", slice_id=None,
                                files=[".claude/memory/shared/x.md"]), toy)
    assert v["verdict"] == "block" and _g10(v)


def test_other_claude_paths_are_not_g10(toy):
    v = handle_event(make_event("pre_change", session="g10",
                                files=[".claude/memory/notes.md"]), toy)
    assert not _g10(v)


def test_g10_is_a_builtin_pre_change_gate():
    from engine.gates import builtin_gates, gates_for_event
    assert "G10" in [g.GATE["id"] for g in builtin_gates()]
    assert "G10" in {g.GATE["id"] for g in gates_for_event("pre_change")}
    assert "G10" not in {g.GATE["id"] for g in gates_for_event("post_change")}
    assert "G10" in {g.GATE["id"]
                     for g in gates_for_event("post_change", degraded=True)}
