"""C5 acceptance: deterministic prioritized blocks under one cap; cut blocks
become pointers; modules are pointers; full module context sits behind
`harness resolve --module`."""
import json

import pytest

from conftest import oversize_slice, run_cli
from engine import (SubstrateMissing, append_jsonl, load_config, read_jsonl,
                    write_jsonl)
from engine.resolver import (MAX_INJECTION_CHARS, over_cap_finding,
                             render_module, resolve)


def _block(out, key):
    return next(b for b in out["blocks"] if b["key"] == key)


def _set_guidance(toy, entry_id, refs):
    path = toy / ".harness" / "registry.jsonl"
    rows = read_jsonl(path)
    for r in rows:
        if r["id"] == entry_id:
            r["guidance_refs"] = refs
    write_jsonl(path, rows)


def test_same_slice_same_substrate_byte_identical(toy):
    config = load_config(toy)
    a = json.dumps(resolve(toy, "slice-042", config), sort_keys=True)
    b = json.dumps(resolve(toy, "slice-042", config), sort_keys=True)
    assert a == b


def test_blocks_come_in_priority_order_under_the_cap(toy):
    out = resolve(toy, "slice-042", load_config(toy))
    assert [b["key"] for b in out["blocks"]] == [
        "decisions", "non-goals", "slice", "modules"]
    assert [b["priority"] for b in out["blocks"]] == [2, 3, 4, 5]
    assert out["cut"] == []
    assert out["injections"] == [b["text"] for b in out["blocks"]]
    assert out["chars"] == len("\n\n".join(out["injections"]))
    assert out["chars"] <= MAX_INJECTION_CHARS


def test_open_findings_lead_the_injection(toy):
    append_jsonl(toy / ".harness" / "parked.jsonl", {
        "slice": "slice-042", "finding": {
            "finding_id": "F-1", "code": "REVIEW_UNCERTAIN",
            "rule_ref": "gate:G5", "message": "OPEN-FINDING-MARKER",
            "severity": "gate", "layer": 2}})
    out = resolve(toy, "slice-042", load_config(toy))
    first = out["blocks"][0]
    assert first["key"] == "findings" and first["priority"] == 1
    assert "OPEN-FINDING-MARKER" in first["text"]


def test_decision_rows_for_declared_domains(toy):
    text = _block(resolve(toy, "slice-042", load_config(toy)), "decisions")["text"]
    assert "D-041" in text and "snake_case verb_noun" in text


def test_non_goals_block_lists_boundaries(toy):
    text = _block(resolve(toy, "slice-042", load_config(toy)), "non-goals")["text"]
    assert "B-legacy" in text and "legacy/**" in text


def test_slice_card_names_goal_statements_and_predicted_files(toy):
    path = toy / ".harness" / "backlog.jsonl"
    rows = read_jsonl(path)
    rows[0]["verifies"] = ["V-orders-1"]
    write_jsonl(path, rows)
    text = _block(resolve(toy, "slice-042", load_config(toy)), "slice")["text"]
    assert "orders service" in text
    assert "V-orders-1" in text and "orders.py" in text


def test_modules_are_pointers_not_shadows_or_guidance(toy):
    out = resolve(toy, "slice-042", load_config(toy))
    text = _block(out, "modules")["text"]
    assert "harness resolve --module telemetry" in text
    assert "harness resolve --module config" in text
    joined = "\n".join(out["injections"])
    assert "def emit_span" not in joined
    assert "SURVIVING-GUIDANCE-MARKER" not in joined


def test_over_cap_decision_rows_survive_and_pointers_replace_lower_blocks(toy):
    oversize_slice(toy)
    out = resolve(toy, "slice-042", load_config(toy))
    assert out["chars"] <= MAX_INJECTION_CHARS < out["demand_chars"]
    assert out["cut"] == ["modules", "slice"]
    assert "D-041" in "\n\n".join(out["injections"])
    pointers = [t for t in out["injections"] if t.startswith("[harness: ")]
    assert len(pointers) == 2
    assert all("harness resolve --slice slice-042" in p for p in pointers)


def test_over_cap_finding_is_advisory_and_names_the_fix():
    f = over_cap_finding("slice-042", ["modules", "slice"], 12000)
    assert f["code"] == "CONTEXT_OVER_CAP" and f["severity"] == "advisory"
    assert f["fix"] == "Split slice slice-042, or shorten its cited decision rows."
    assert len(f["message"].split()) <= 25


def test_cli_resolve_slice_has_no_cap(toy):
    oversize_slice(toy)
    proc = run_cli("resolve", "--slice", "slice-042", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["cut"] == [] and out["chars"] > MAX_INJECTION_CHARS
    assert out["acceptance_python"]


def test_module_renders_shadow_and_surviving_guidance(toy):
    text = render_module(toy, "telemetry", load_config(toy))["text"]
    assert "=== shadow:telemetry" in text and "emit_span" in text
    assert "SURVIVING-GUIDANCE-MARKER" in text
    assert "SUPERSEDABLE-GUIDANCE-MARKER" not in text


def test_planned_module_uses_guidance_not_shadow(toy):
    text = render_module(toy, "config", load_config(toy))["text"]
    assert "Telemetry section one" in text
    assert "=== shadow:config" not in text


def test_module_guidance_counts_a_repeated_anchor_once(toy):
    _set_guidance(toy, "orders", ["adr/007-telemetry.md#s1",
                                  "adr/007-telemetry.md#s1",
                                  "adr/007-telemetry.md#s3"])
    text = render_module(toy, "orders", load_config(toy))["text"]
    assert text.count("=== guidance adr/007-telemetry.md#s1") == 1
    assert "=== guidance adr/007-telemetry.md#s3" in text


def test_module_missing_anchor_is_a_reported_fallback(toy):
    _set_guidance(toy, "orders", ["adr/007-telemetry.md#nope"])
    out = render_module(toy, "orders", load_config(toy))
    fallback = [d for d in out["dropped"] if d["kind"] == "anchor-missing"]
    assert fallback and fallback[0]["ids"] == ["adr/007-telemetry.md#nope"]
    assert "whole file" in fallback[0]["reason"]


def test_cli_resolve_module(toy):
    proc = run_cli("resolve", "--module", "telemetry", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "emit_span" in json.loads(proc.stdout)["text"]


def test_missing_guidance_file_fails_loud_for_the_module(toy):
    (toy / "adr" / "007-telemetry.md").unlink()
    with pytest.raises(SubstrateMissing, match="guidance_ref"):
        render_module(toy, "telemetry", load_config(toy))


def test_unknown_module_fails_loud(toy):
    with pytest.raises(SubstrateMissing, match="ghost"):
        render_module(toy, "ghost", load_config(toy))


def test_missing_declared_dep_fails_loud(toy):
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["declares_dep"].append("ghost")
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    with pytest.raises(SubstrateMissing, match="ghost"):
        resolve(toy, "slice-042", load_config(toy))


def test_open_findings_block_shows_the_fix(toy):
    append_jsonl(toy / ".harness" / "parked.jsonl", {
        "slice": "slice-042", "finding": {
            "finding_id": "F-2", "code": "UNDECLARED_FILE",
            "rule_ref": "gate:G3", "message": "rogue.py is undeclared.",
            "fix": "Add rogue.py to predicted_files.",
            "severity": "gate", "layer": 2}})
    text = _block(resolve(toy, "slice-042", load_config(toy)), "findings")["text"]
    assert ("[UNDECLARED_FILE gate:G3] rogue.py is undeclared.\n"
            "  Fix: Add rogue.py to predicted_files.") in text


def test_open_findings_block_renders_inject_lines_after_the_fix(toy):
    append_jsonl(toy / ".harness" / "parked.jsonl", {
        "slice": "slice-042", "finding": {
            "finding_id": "F-3", "code": "REVIEW_FINDING",
            "rule_ref": "decision:D-041", "message": "orders.py breaks D-041.",
            "fix": "Rename the span.",
            "inject": ["Failure scenario: a filter misses every span."],
            "severity": "gate", "layer": 2}})
    text = _block(resolve(toy, "slice-042", load_config(toy)), "findings")["text"]
    assert ("  Fix: Rename the span.\n"
            "Failure scenario: a filter misses every span.") in text


def test_one_long_finding_line_is_clipped_so_it_cannot_crowd_out_decisions(toy):
    append_jsonl(toy / ".harness" / "parked.jsonl", {
        "slice": "slice-042", "finding": {
            "finding_id": "F-2", "code": "REVIEW_UNCERTAIN",
            "rule_ref": "gate:G5", "message": "short", "severity": "gate",
            "layer": 2, "inject": ["Evidence: " + "x" * 5000]}})
    text = _block(resolve(toy, "slice-042", load_config(toy)), "findings")["text"]
    line = [l for l in text.splitlines() if l.startswith("Evidence: ")][0]
    assert len(line) <= 401 and line.endswith("…")
