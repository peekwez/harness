"""§8 acceptance: mandatory attempt fields; compaction to durable; flush."""
import pytest

from engine import HarnessError, memory, read_jsonl


def test_attempt_requires_approach_outcome_why(toy):
    with pytest.raises(HarnessError, match="approach"):
        memory.make_entry("slice-042", "attempt", "tried X", attempt={})
    with pytest.raises(HarnessError, match="invalid"):
        memory.make_entry("slice-042", "attempt", "tried X",
                          attempt={"approach": "a", "outcome": "great", "why": "w"})
    e = memory.make_entry("slice-042", "attempt", "tried sqlite locks",
                          attempt={"approach": "advisory locks",
                                   "outcome": "abandoned",
                                   "why": "worktrees partition instead"})
    assert e["kind"] == "attempt" and e["scope"] == "session"


def test_invalid_kind_fails_loud(toy):
    with pytest.raises(HarnessError):
        memory.make_entry("slice-042", "vibes", "x")


def test_compact_promotes_attempts_and_deletes_session_file(toy):
    memory.write_entry(toy, memory.make_entry(
        "slice-042", "attempt", "tried polling",
        attempt={"approach": "poll", "outcome": "failed", "why": "racy"},
        edges=[{"type": "remembers", "to": "module:telemetry"}]))
    memory.write_entry(toy, memory.make_entry(
        "slice-042", "reasoning", "ephemeral scratch note"))
    sp = memory.session_path(toy, "slice-042")
    assert sp.exists()

    result = memory.compact_to_durable(toy, "slice-042", commit="abc123")
    assert result["total"] == 2
    assert len(result["promoted"]) == 1  # attempt survives; bare reasoning doesn't
    assert not sp.exists(), "session file must be deleted after compaction"

    durable = read_jsonl(memory.durable_path(toy))
    kinds = [d["kind"] for d in durable]
    assert "attempt" in kinds and "observation" in kinds  # + summary
    promoted = next(d for d in durable if d["kind"] == "attempt")
    assert promoted["scope"] == "durable" and promoted["commit"] == "abc123"

    from engine.graph import load_edges
    edges = load_edges(toy)
    assert any(e["type"] == "remembers" and e["to"] == "module:telemetry"
               for e in edges)


def test_flush_reports_entries(toy):
    memory.write_entry(toy, memory.make_entry("slice-042", "observation", "x"))
    out = memory.flush(toy, "slice-042")
    assert out["entries"] == 1
