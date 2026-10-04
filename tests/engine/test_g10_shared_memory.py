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
    assert "harness memory promote" in finding["fix"]
    assert len(finding["message"].split()) <= 25


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


SHARED_DIFF = """diff --git a/.claude/memory/shared/x.md b/.claude/memory/shared/x.md
new file mode 100644
--- /dev/null
+++ b/.claude/memory/shared/x.md
@@ -0,0 +1 @@
+a fact a human promoted
"""


def test_review_over_committed_promotion_is_not_g10(toy):
    """A promoted fact rides the slice commit; review reads the diff, not a
    tool edit, so G10 stays quiet even in degraded mode (final fix I1)."""
    from engine import load_config
    from engine.review import assemble
    config = load_config(toy)
    config.setdefault("gates", {})["degraded_mode"] = True
    facts = assemble(toy, SHARED_DIFF, "slice-042", config)
    assert not [f for f in facts["gate_findings"]
                if f["code"] == "SHARED_MEMORY_WRITE"]


def test_degraded_host_edit_into_shared_memory_still_blocks(toy):
    import yaml
    cfg = toy / ".harness" / "config.yaml"
    doc = yaml.safe_load(cfg.read_text()) or {}
    doc.setdefault("gates", {})["degraded_mode"] = True
    cfg.write_text(yaml.safe_dump(doc, sort_keys=False))
    v = handle_event(make_event("post_change", session="g10",
                                files=[".claude/memory/shared/x.md"]), toy)
    assert v["verdict"] == "block" and _g10(v)


def test_host_event_cannot_claim_the_review_source(toy):
    evt = make_event("pre_change", session="g10",
                     files=[".claude/memory/shared/x.md"])
    evt["payload"]["source"] = "review"
    v = handle_event(evt, toy)
    assert v["verdict"] == "block" and _g10(v)
