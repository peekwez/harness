"""Regression tests for the rt-pilot field report (#1–#13): every observed
silent-degradation instance becomes a test."""
import json

import pytest

from conftest import loaded_context, make_event, run_cli
from engine import read_jsonl, write_jsonl
from engine.compiler import (author_gate, compile_substrate, extract_non_goals,
                             _unresolved_open_questions)


# ---------------------------------------------------------------- #1
def test_author_gate_recognizes_resolution_markers(toy):
    doc = toy / "docs" / "architecture.md"
    doc.parent.mkdir()
    doc.write_text(
        "~~[open-question] Exact max count cap value~~ → **resolved: cap = 100**\n"
        "[open-question] Retention window? [resolved: adr/007]\n"
        "[open-question] Sharding? -> resolved in ADR-003\n"
        "[open-question] Ownership model? deferred: kwesi\n"
        "Prose explaining that `[open-question]` tokens map to gaps.\n")
    assert _unresolved_open_questions(doc.read_text()) == []
    result = author_gate(toy, working_doc=doc)
    assert not any("open question" in g for g in result["gaps"]), result["gaps"]

    doc.write_text("[open-question] Genuinely unresolved thing?\n")
    result = author_gate(toy, working_doc=doc)
    assert any("Genuinely unresolved" in g for g in result["gaps"])


# ---------------------------------------------------------------- #2
def test_non_goal_multiline_block_keeps_patterns():
    text = ("## Implementation\n\n"
            "[non-goal] Rewriting the legacy exporter is out of scope,\n"
            "including everything under `legacy/**` and forbid: `vendor/exporter.py`.\n\n"
            "Other paragraph.\n")
    blocks = extract_non_goals(text)
    assert len(blocks) == 1
    block_text, patterns, _descriptive = blocks[0]
    assert "including everything" in block_text  # not truncated at line 1
    assert patterns == ["legacy/**", "vendor/exporter.py"]


def test_non_goal_token_in_code_span_is_prose():
    text = ("The mapping is: `[non-goal]` → boundaries.jsonl rows.\n\n"
            "Also \"[non-goal] blocks here compile into G3 boundaries\" is a\n"
            "sentence quoted from docs — wait, this one IS a directive.\n")
    blocks = extract_non_goals(text)
    # backticked token ignored; bare token still counts
    assert len(blocks) == 1
    assert "compile into G3" in blocks[0][0]


def test_template_adrs_never_compile(toy):
    (toy / "adr" / "000-template.md").write_text(
        '---\nid: "000"\n---\n\n[non-goal] example text with `fake/**` glob\n')
    compile_substrate(toy)
    boundaries = read_jsonl(toy / ".harness" / "boundaries.jsonl")
    assert not any(b.get("source_adr") == "000" for b in boundaries)


def test_pattern_less_non_goal_warns(toy):
    adr = (toy / "adr" / "008-scope.md")
    adr.write_text('---\nid: "008"\n---\n\n[non-goal] No mobile clients ever\n')
    report = compile_substrate(toy)
    assert any("no backticked path" in w for w in report["warnings"])


# ---------------------------------------------------------------- #3
def test_boundaries_regenerate_instead_of_accumulate(toy):
    r1 = compile_substrate(toy)
    n1 = len(read_jsonl(toy / ".harness" / "boundaries.jsonl"))
    # fix the source text -> recompile -> count must not grow, old id gone
    adr = toy / "adr" / "007-telemetry.md"
    adr.write_text(adr.read_text().replace(
        "Rewriting the legacy exporter under `legacy/**` is out of scope.",
        "Touching the legacy exporter tree `legacy/**` is out of scope."))
    compile_substrate(toy)
    rows = read_jsonl(toy / ".harness" / "boundaries.jsonl")
    assert len(rows) == n1, "derived file must regenerate, not accumulate"
    assert not any("Rewriting" in b["text"] for b in rows)
    assert any("Touching" in b["text"] for b in rows)


# ---------------------------------------------------------------- #4
def test_missing_extraction_deps_degrade_not_crash(toy, monkeypatch):
    from engine.extractor import engine as ex
    from engine import load_config
    monkeypatch.setattr(ex, "deps_available", lambda: False)
    (toy / "orders.py").write_text("def create_order(s):\n    return s\n")
    shadow, findings = ex.extract_path(toy, toy / "orders.py", load_config(toy))
    assert shadow["exports"] == "unknown"  # degenerate, not an exception
    codes = {f["code"] for f in findings}
    assert "MISSING_DEPENDENCY" in codes
    assert all(f["severity"] == "advisory" for f in findings)

    # unit_complete (the Stop path that hard-blocked in the field) stays unblocked
    from engine.gates.g7_derivation import derivation_findings
    g7 = derivation_findings(toy, load_config(toy))
    assert all(f["severity"] == "advisory" for f in g7)
    assert any(f["code"] == "MISSING_DEPENDENCY" for f in g7)


def test_doctor_reports_deps(toy):
    proc = run_cli("doctor", root=toy)
    out = json.loads(proc.stdout)
    assert proc.returncode == 0 and out["healthy"]
    assert set(out["deps"]) == {"pyyaml", "tree-sitter", "tree-sitter-language-pack"}


# ---------------------------------------------------------------- #5
def test_replaces_prunes_scaffolded_planned_entries(toy):
    rows = read_jsonl(toy / ".harness" / "registry.jsonl")
    rows += [{"id": "logging", "kind": "logging", "status": "planned",
              "module_id": None, "source": None, "source_hash": None,
              "shadow": None, "guidance_refs": [], "supersedes_guidance": [],
              "manifest": [], "signature_digest": None}]
    write_jsonl(toy / ".harness" / "registry.jsonl", rows)
    (toy / "adr" / "009-obs.md").write_text(
        '---\nid: "009"\nabstractions:\n  - id: observability\n'
        '    kind: telemetry\n    replaces: [logging]\n---\nbody\n')
    report = compile_substrate(toy)
    assert "logging" in report["pruned"]
    ids = {e["id"] for e in read_jsonl(toy / ".harness" / "registry.jsonl")}
    assert "logging" not in ids and "observability" in ids
    # built/sourced entries are protected: telemetry has a source
    (toy / "adr" / "010-bad.md").write_text(
        '---\nid: "010"\nabstractions:\n  - id: megamod\n    kind: other\n'
        '    replaces: [telemetry]\n---\nbody\n')
    report = compile_substrate(toy)
    assert "telemetry" not in report["pruned"]
    assert any("not pruned" in w for w in report["warnings"])


# ---------------------------------------------------------------- #6
def test_api_surface_gaps_reported_and_gate_blocks(toy):
    adr = toy / "adr" / "011-api.md"
    adr.write_text('---\nid: "011"\napi_surface:\n  - "GET /orders"\n---\nbody\n')
    report = compile_substrate(toy)
    # contracts/api.yaml exists (authored) and lacks /orders -> gap, not rewrite
    assert any("/orders" in g for g in report["contract_gaps"])
    before = (toy / "contracts" / "api.yaml").read_text()
    assert "/orders" not in before, "authored contract must not be rewritten"
    result = author_gate(toy)
    assert any("GET /orders" in g for g in result["gaps"])


def test_api_surface_stub_created_for_new_contract(toy):
    adr = toy / "adr" / "012-newapi.md"
    adr.write_text('---\nid: "012"\ncontract: billing\n'
                   'api_surface:\n  - "POST /invoices"\n---\nbody\n')
    report = compile_substrate(toy)
    assert "contracts/billing.yaml" in report["contracts"]
    import yaml
    doc = yaml.safe_load((toy / "contracts" / "billing.yaml").read_text())
    assert "post" in doc["paths"]["/invoices"]


# ---------------------------------------------------------------- #7
def test_epoch_timestamp_never_propagates(toy):
    rows = read_jsonl(toy / ".harness" / "decisions.jsonl")
    rows[0]["created"] = "1970-01-01T00:00:00+00:00"
    write_jsonl(toy / ".harness" / "decisions.jsonl", rows)
    compile_substrate(toy)
    d41 = next(d for d in read_jsonl(toy / ".harness" / "decisions.jsonl")
               if d["id"] == "D-041")
    assert not d41["created"].startswith("1970-")


def test_changed_row_gets_updated_stamp(toy):
    adr = toy / "adr" / "007-telemetry.md"
    adr.write_text(adr.read_text().replace(
        "snake_case verb_noun; never free-form strings.",
        "snake_case verb_noun; prefixes per service."))
    compile_substrate(toy)
    d41 = next(d for d in read_jsonl(toy / ".harness" / "decisions.jsonl")
               if d["id"] == "D-041")
    assert "updated" in d41 and d41["answer"].endswith("per service.")


# ---------------------------------------------------------------- #8
def test_author_gate_blocks_placeholders_and_dangling_deps(toy):
    rows = read_jsonl(toy / ".harness" / "decisions.jsonl")
    rows.append({"id": "D-777", "domain": "config", "question": "q",
                 "answer": "EDIT ME: pick one", "adr_ref": None,
                 "origin": "phase0", "created": "1970-01-01T00:00:00+00:00"})
    write_jsonl(toy / ".harness" / "decisions.jsonl", rows)
    backlog = read_jsonl(toy / ".harness" / "backlog.jsonl")
    backlog.append({"id": "slice-999", "spec": "spec-000",
                    "title": "EDIT ME: build something", "status": "planned",
                    "declares_dep": ["ghost-module"], "acceptance": [],
                    "predicted_files": [], "context_cost_estimate": 0,
                    "depends_on": [], "worktree": None})
    write_jsonl(toy / ".harness" / "backlog.jsonl", backlog)
    result = author_gate(toy)
    gaps = "\n".join(result["gaps"])
    assert "EDIT ME" in gaps
    assert "placeholder epoch" in gaps
    assert "ghost-module" in gaps


def test_close_slice_blocks_on_placeholder(toy):
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["title"] = "EDIT ME: orders service"
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    proc = run_cli("close-slice", "--slice", "slice-042", root=toy)
    assert proc.returncode == 1
    assert "EDIT ME" in proc.stdout


# ---------------------------------------------------------------- #9
def test_backlog_auto_adds_acceptance_to_predicted(toy):
    proc = run_cli("backlog", root=toy)
    assert proc.returncode == 0, proc.stderr
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    sl = next(r for r in rows if r["id"].startswith("slice-042"))
    assert "tests/slices/042_orders.py" in sl["predicted_files"]


# ---------------------------------------------------------------- #10 + #11
def test_decision_rows_match_dep_id_even_when_kind_coerced(toy):
    (toy / "adr" / "013-obs.md").write_text(
        '---\nid: "013"\nabstractions:\n  - id: observability\n'
        '    kind: observability\n---\nbody\n')
    report = compile_substrate(toy)
    assert any("coerced" in w for w in report["warnings"])  # #11: loud, not silent
    rows = read_jsonl(toy / ".harness" / "decisions.jsonl")
    rows.append({"id": "D-090", "domain": "observability",
                 "question": "Span budget?", "answer": "100 per request.",
                 "adr_ref": "adr/013-obs.md", "origin": "phase0",
                 "created": "2026-01-01T00:00:00+00:00"})
    write_jsonl(toy / ".harness" / "decisions.jsonl", rows)
    backlog = read_jsonl(toy / ".harness" / "backlog.jsonl")
    backlog[0]["declares_dep"].append("observability")
    write_jsonl(toy / ".harness" / "backlog.jsonl", backlog)

    from engine import load_config
    from engine.resolver import resolve
    out = resolve(toy, "slice-042", load_config(toy))
    assert "decision:D-090" in out["context_loaded"], \
        "rows must match the dep id even when its kind was coerced to 'other'"


# ------------------------------------------------- walkthrough regression
def test_close_refreshes_built_entry_hash_after_acked_drift(toy):
    """A slice that legitimately modifies a BUILT dep (G6-acked) must leave
    the registry hash-consistent, or verify fails HASH_MISMATCH forever
    (found live in the todo-api walkthrough)."""
    from engine.events import handle_event
    from engine.gates.g6_drift import acknowledge
    session = "refresh"
    run_cli("slice", "--slice", "slice-042", "--session", session, root=toy)
    loaded_context(toy, session=session)
    (toy / "orders.py").write_text(
        "import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
        "    telemetry.emit_span('create_order', {'sku': sku})\n"
        "    return {'sku': sku}\n")
    # modify the BUILT telemetry module mid-slice
    (toy / "telemetry.py").write_text(
        (toy / "telemetry.py").read_text() + "\n\ndef flush():\n    return None\n")
    handle_event(make_event("post_change", session=session,
                            files=["orders.py", "telemetry.py"]), toy)
    handle_event(make_event("unit_complete", session=session), toy)
    acknowledge(toy, "slice-042", "telemetry", "flush approved")
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["predicted_files"].append("telemetry.py")
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    from conftest import git
    git(toy, "add", "-A"); git(toy, "commit", "-qm", "slice-042")
    head = git(toy, "rev-parse", "HEAD").stdout.strip()
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", head, root=toy)
    out = json.loads(proc.stdout)
    assert proc.returncode == 0, proc.stdout
    assert "telemetry" in out["registry_refreshed"], out
    proc = run_cli("verify", root=toy)
    v = json.loads(proc.stdout)
    assert v["passed"], [f["code"] for f in v["findings"]]


def test_compile_adopts_source_into_seeded_planned_entries(toy):
    """A seeded planned entry (source: null) must adopt the ADR's source —
    otherwise it never qualifies for the planned->built flip at close-slice
    (found live in the todo-api walkthrough: registry_flipped came back [])."""
    rows = read_jsonl(toy / ".harness" / "registry.jsonl")
    rows.append({"id": "payments", "kind": "component", "status": "planned",
                 "module_id": None, "source": None, "source_hash": None,
                 "shadow": None, "guidance_refs": [], "supersedes_guidance": [],
                 "manifest": [], "signature_digest": None})
    write_jsonl(toy / ".harness" / "registry.jsonl", rows)
    (toy / "adr" / "014-pay.md").write_text(
        '---\nid: "014"\nabstractions:\n  - id: payments\n    kind: component\n'
        '    source: payments.py\n    manifest: [payments.py]\n---\nbody\n')
    compile_substrate(toy)
    entry = next(e for e in read_jsonl(toy / ".harness" / "registry.jsonl")
                 if e["id"] == "payments")
    assert entry["source"] == "payments.py"
    assert entry["manifest"] == ["payments.py"]



def test_denied_pre_change_records_no_phantom_touch(toy):
    """A blocked edit never happened: it must not demand G3 reconciliation
    at close-slice (found live in the todo-api walkthrough)."""
    from engine.events import Sidecar, handle_event
    loaded_context(toy, session="phantom")
    v = handle_event(make_event("pre_change", session="phantom",
                                files=["legacy/exporter.py"]), toy)  # boundary deny
    assert v["verdict"] == "block"
    sc = Sidecar(toy)
    try:
        assert "legacy/exporter.py" not in sc.touched_paths(slice_id="slice-042")
    finally:
        sc.close()
    v2 = handle_event(make_event("pre_change", session="phantom",
                                 files=["orders.py"]), toy)  # allowed
    assert v2["verdict"] == "allow"
    sc = Sidecar(toy)
    try:
        assert "orders.py" in sc.touched_paths(slice_id="slice-042")
    finally:
        sc.close()


# ---------------------------------------------------------------- #12 + #13
def test_init_git_dx(tmp_path):
    import subprocess
    target = tmp_path / "fresh"
    target.mkdir()
    (target / "app.py").write_text("x = 1\n")
    subprocess.run(["git", "init", "-q", str(target)], capture_output=True)
    proc = run_cli("init", root=target)
    assert proc.returncode == 0
    assert "no commits yet" in proc.stdout  # #12: worktree hint
    ref = subprocess.run(["git", "-C", str(target), "config", "notes.displayRef"],
                         capture_output=True, text=True).stdout.strip()
    assert ref == "refs/notes/harness"  # #13: notes discoverable


def test_close_slice_names_notes_ref(toy):
    from conftest import git
    from engine.events import handle_event
    session = "notes-ref"
    run_cli("slice", "--slice", "slice-042", "--session", session, root=toy)
    loaded_context(toy, session=session)
    (toy / "orders.py").write_text(
        "import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
        "    telemetry.emit_span('create_order', {'sku': sku})\n"
        "    return {'sku': sku}\n")
    handle_event(make_event("post_change", session=session,
                            files=["orders.py"]), toy)
    handle_event(make_event("unit_complete", session=session), toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "slice-042")
    head = git(toy, "rev-parse", "HEAD").stdout.strip()
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", head, root=toy)
    out = json.loads(proc.stdout)
    assert out["notes_ref"] == "refs/notes/harness"
    assert "git notes --ref=refs/notes/harness show" in out["notes_hint"]
