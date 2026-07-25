"""M5 acceptance: brainstorm doc compiles to decisions/registry/boundaries;
author-gate blocks on seeded gaps; compile chain e2e on the telemetry domain
(ADR frontmatter -> decision row -> G-check citing it)."""
import pytest

from engine import HarnessError, read_jsonl
from engine.compiler import author_gate, compile_substrate, parse_frontmatter


def test_compile_adr_to_substrate(toy):
    report = compile_substrate(toy)
    assert "adr/007-telemetry.md" in report["adrs"]
    decisions = {d["id"]: d for d in read_jsonl(toy / ".harness" / "decisions.jsonl")}
    assert decisions["D-041"]["origin"] == "phase0"
    assert decisions["D-041"]["adr_ref"] == "adr/007-telemetry.md"
    registry = {e["id"]: e for e in read_jsonl(toy / ".harness" / "registry.jsonl")}
    assert registry["telemetry"]["kind"] == "telemetry"
    boundaries = read_jsonl(toy / ".harness" / "boundaries.jsonl")
    assert any("legacy/**" in b["patterns"] for b in boundaries)


def test_compile_idempotent(toy):
    compile_substrate(toy)
    first = (toy / ".harness" / "decisions.jsonl").read_bytes()
    compile_substrate(toy)
    assert (toy / ".harness" / "decisions.jsonl").read_bytes() == first


def test_adjudicated_rows_outrank_recompiled_phase0(toy):
    from engine import write_jsonl
    write_jsonl(toy / ".harness" / "decisions.jsonl", [
        {"id": "D-041", "domain": "telemetry", "question": "Span naming?",
         "answer": "ADJUDICATED ANSWER", "adr_ref": None,
         "origin": "adjudication", "created": "2026-01-02T00:00:00+00:00"}])
    compile_substrate(toy)
    rows = {d["id"]: d for d in read_jsonl(toy / ".harness" / "decisions.jsonl")}
    assert rows["D-041"]["answer"] == "ADJUDICATED ANSWER"


def test_malformed_frontmatter_fails_loud(toy):
    (toy / "adr" / "008-bad.md").write_text("---\nid: [unclosed\n---\nbody\n")
    with pytest.raises(HarnessError):
        compile_substrate(toy)


def test_missing_decision_row_fields_fail_loud(toy):
    (toy / "adr" / "009-partial.md").write_text(
        '---\nid: "009"\nstatus: accepted\ndomains: [x]\n'
        'decision_table_rows:\n  - id: D-900\n    domain: x\n---\nbody\n')
    with pytest.raises(HarnessError, match="question"):
        compile_substrate(toy)


def test_author_gate_blocks_on_seeded_gaps(toy):
    doc = toy / "docs" / "architecture.md"
    doc.parent.mkdir()
    doc.write_text("[open-question] Who owns retention policy?\n")
    result = author_gate(toy, working_doc=doc)
    assert not result["passed"]
    assert any("open question" in g for g in result["gaps"])
    # config domain has no decision row in the toy substrate
    assert any("config" in g for g in result["gaps"])


def test_author_gate_passes_when_gaps_closed(toy):
    from engine import write_jsonl, read_jsonl
    doc = toy / "docs" / "architecture.md"
    doc.parent.mkdir()
    doc.write_text("[open-question] retention? deferred: kwesi\n")
    rows = read_jsonl(toy / ".harness" / "decisions.jsonl")
    rows += [{"id": "D-050", "domain": "config", "question": "q", "answer": "a",
              "adr_ref": None, "origin": "phase0", "created": "2026-01-01T00:00:00+00:00"},
             {"id": "D-051", "domain": "component", "question": "q", "answer": "a",
              "adr_ref": None, "origin": "phase0", "created": "2026-01-01T00:00:00+00:00"}]
    write_jsonl(toy / ".harness" / "decisions.jsonl", rows)
    result = author_gate(toy, working_doc=doc)
    assert result["passed"], result["gaps"]


def test_compile_chain_telemetry_end_to_end(toy):
    """ADR frontmatter -> decision row -> G-check citing it (M5 gate)."""
    compile_substrate(toy)
    # decision row exists and reaches the resolver
    from engine import load_config
    from engine.resolver import resolve
    out = resolve(toy, "slice-042", load_config(toy))
    assert "decision:D-041" in out["context_loaded"]
    # the [non-goal] boundary compiled from the same ADR blocks with adr ref
    from conftest import loaded_context, make_event
    from engine.events import handle_event
    loaded_context(toy, session="chain")
    v = handle_event(make_event("pre_change", session="chain",
                                files=["legacy/exporter.py"]), toy)
    hits = [f for f in v["findings"] if f["code"] == "NON_GOAL_VIOLATION"]
    assert hits and hits[0]["rule_ref"] == "adr:007"


def test_parse_frontmatter_shapes():
    fm, body = parse_frontmatter("---\nid: '1'\n---\nbody here\n")
    assert fm == {"id": "1"} and body.strip() == "body here"
    fm, body = parse_frontmatter("no frontmatter")
    assert fm == {} and body == "no frontmatter"
    with pytest.raises(HarnessError):
        parse_frontmatter("---\nid: 1\nnever closed")
