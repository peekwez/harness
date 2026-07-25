"""Regression tests for rt-pilot field report round 2 (#14–#22)."""
import json
import os
import sys

import pytest

from conftest import git, loaded_context, make_event, run_cli
from engine import load_config, read_jsonl, write_jsonl
from engine.compiler import author_gate, compile_substrate, extract_non_goals
from engine.events import Sidecar, handle_event


# ---------------------------------------------------------------- #19
def test_out_of_root_paths_never_crash_the_stop_hook(toy):
    session = "oor"
    loaded_context(toy, session=session)
    # post_change with an absolute out-of-root path (scratchpad workaround)
    handle_event(make_event("post_change", session=session,
                            files=["/tmp/definitely-outside/scratch.py"]), toy)
    sc = Sidecar(toy)
    try:
        assert not any("scratch.py" in t for t in
                       sc.touched_paths(session_id=session))
        # simulate a poison row from an older build: must be skipped, not crash
        sc.touch(session, "slice-042", ["/tmp/definitely-outside/poison.py"])
    finally:
        sc.close()
    v = handle_event(make_event("unit_complete", session=session), toy)
    assert v["verdict"] in ("allow", "allow_with_findings", "block")  # no exception


def test_extract_path_outside_root_is_advisory_not_crash(toy, tmp_path):
    from engine.extractor.engine import extract_path
    outside = tmp_path / "elsewhere.py"
    outside.write_text("x = 1\n")
    shadow, findings = extract_path(toy, outside, load_config(toy))
    assert shadow is None
    assert findings and findings[0]["severity"] == "advisory"


# ---------------------------------------------------------------- #15
def test_resolver_skips_superseded_adr_guidance(toy):
    (toy / "adr" / "009-push-model.md").write_text(
        '---\nid: "009"\nstatus: accepted\nsupersedes: ["007"]\n---\n'
        '# ADR-009\nNew push model replaces ADR-007 guidance.\n')
    from engine.resolver import resolve
    out = resolve(toy, "slice-042", load_config(toy))
    joined = "\n".join(out["injections"])
    assert "SURVIVING-GUIDANCE-MARKER" not in joined  # adr/007 is out of force
    assert "adr:007" not in out["context_loaded"]
    assert any(d.get("kind") == "guidance-superseded" for d in out["dropped"]), \
        "the drop must be visible, not silent"


# ---------------------------------------------------------------- #14
def test_compile_reconciles_refs_and_kind_on_recompile(toy):
    compile_substrate(toy)
    reg = {e["id"]: e for e in read_jsonl(toy / ".harness" / "registry.jsonl")}
    # telemetry is BUILT: its authored refs are preserved (the resolver skips
    # out-of-force ones at read time); planned entries get reconciled below
    assert reg["telemetry"]["guidance_refs"] == [
        "adr/007-telemetry.md#s2", "adr/007-telemetry.md#s3"]

    # supersede ADR-007 with ADR-010 re-authoring telemetry under a new ref
    (toy / "adr" / "010-obs.md").write_text(
        '---\nid: "010"\nstatus: accepted\nsupersedes: ["007"]\n'
        'abstractions:\n  - id: telemetry\n    kind: telemetry\n---\nbody\n')
    report = compile_substrate(toy)
    assert "adr/007-telemetry.md" in report["skipped_superseded"]
    reg = {e["id"]: e for e in read_jsonl(toy / ".harness" / "registry.jsonl")}
    # planned entries: refs REPLACED from in-force ADRs; superseded ref gone
    assert reg["config"]["guidance_refs"] == [], reg["config"]
    # telemetry is BUILT: refs untouched structurally, but the resolver skips
    # them at read time (tested above) — built entries are not rewritten here

    # kind change propagates on recompile
    (toy / "adr" / "010-obs.md").write_text(
        '---\nid: "010"\nstatus: accepted\nsupersedes: ["007"]\n'
        'abstractions:\n  - id: orders\n    kind: util\n---\nbody\n')
    compile_substrate(toy)
    reg = {e["id"]: e for e in read_jsonl(toy / ".harness" / "registry.jsonl")}
    assert reg["orders"]["kind"] == "util"


# ---------------------------------------------------------------- #2-recurrence
def test_descriptive_path_in_non_goal_is_not_a_blocking_glob():
    blocks = extract_non_goals(
        "[non-goal] Backend wiring lives in `infra/otel-config.yaml`, not here.\n")
    (_text, patterns, descriptive) = blocks[0]
    assert patterns == []
    assert descriptive == ["infra/otel-config.yaml"]

    blocks = extract_non_goals(
        "[non-goal] Never edit the collector config. forbid: `infra/otel-config.yaml`\n")
    assert blocks[0][1] == ["infra/otel-config.yaml"]  # explicit forbid: enforces

    blocks = extract_non_goals("[non-goal] Keep out of `legacy/**` entirely.\n")
    assert blocks[0][1] == ["legacy/**"]  # wildcard = explicit intent


def test_descriptive_path_compiles_to_warning_not_block(toy):
    (toy / "adr" / "011-wiring.md").write_text(
        '---\nid: "011"\nstatus: accepted\n---\n# ADR-011\n## Implementation\n\n'
        '[non-goal] Wiring lives in `infra/collector.yaml`, slices create it.\n')
    report = compile_substrate(toy)
    assert any("descriptively" in w and "infra/collector.yaml" in w
               for w in report["warnings"])
    boundaries = read_jsonl(toy / ".harness" / "boundaries.jsonl")
    assert not any("infra/collector.yaml" in b.get("patterns", [])
                   for b in boundaries)


def test_g3_non_goal_block_is_overridable(toy):
    session = "g3ovr"
    loaded_context(toy, session=session)
    v = handle_event(make_event("pre_change", session=session,
                                files=["legacy/exporter.py"]), toy)
    assert v["verdict"] == "block"
    bid = next(b["id"] for b in read_jsonl(toy / ".harness" / "boundaries.jsonl")
               if "legacy/**" in b["patterns"])
    assert f"boundary:{bid}" in json.dumps(v["findings"]), \
        "the block must name its own override target"
    run_cli("gates", "override", "--slice", "slice-042",
            "--target", f"boundary:{bid}",
            "--justification", "one-off migration approved by kwesi", root=toy)
    v2 = handle_event(make_event("pre_change", session=session,
                                 files=["legacy/exporter.py"]), toy)
    assert v2["verdict"] != "block"
    assert any(f["code"] == "NON_GOAL_VIOLATION" and f["severity"] == "advisory"
               for f in v2["findings"])  # audited, not silent


# ---------------------------------------------------------------- #21
def test_docs_edits_are_exempt_and_g3_consults_overrides(toy):
    session = "docs-ex"
    loaded_context(toy, session=session)
    v = handle_event(make_event("pre_change", session=session,
                                files=["docs/notes.md"]), toy)
    assert not any(f["code"] == "UNDECLARED_FILE" for f in v["findings"])

    # an undeclared file reconciles via a recorded file: override
    run_cli("gates", "override", "--slice", "slice-042",
            "--target", "file:rogue.py",
            "--justification", "meta helper agreed in review", root=toy)
    v2 = handle_event(make_event("pre_change", session=session,
                                 files=["rogue.py"]), toy)
    assert not any(f["code"] == "UNDECLARED_FILE" for f in v2["findings"])


# ---------------------------------------------------------------- #18 + #22
def test_default_binding_reaches_unknown_hook_sessions(toy):
    run_cli("slice", "--slice", "slice-042", root=toy)  # no --session
    # the hook arrives with the host's real UUID nobody typed anywhere
    v = handle_event({"event": "session_start",
                      "session_id": "87ab4fe2-real-host-uuid",
                      "work_unit_id": None,
                      "payload": {"files": [], "context_loaded": [],
                                  "diff": None, "prompt": None}}, toy)
    assert v["injections"], "default binding must resolve the work unit"


def test_slice_release_and_close_unbinds(toy):
    run_cli("slice", "--slice", "slice-042", "--session", "s-r", root=toy)
    proc = run_cli("slice", "--release", "--slice", "slice-042", root=toy)
    assert json.loads(proc.stdout)["released"] >= 2  # session + __default__
    sc = Sidecar(toy)
    try:
        assert sc.state_get("__default__", "active_slice") is None
    finally:
        sc.close()

    # close-slice also releases (full ceremony)
    session = "s-close2"
    run_cli("slice", "--slice", "slice-042", "--session", session, root=toy)
    loaded_context(toy, session=session)
    (toy / "orders.py").write_text(
        "import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
        "    telemetry.emit_span('create_order', {'sku': sku})\n"
        "    return {'sku': sku}\n")
    handle_event(make_event("post_change", session=session,
                            files=["orders.py"]), toy)
    handle_event(make_event("unit_complete", session=session), toy)
    git(toy, "add", "-A"); git(toy, "commit", "-qm", "s")
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", git(toy, "rev-parse", "HEAD").stdout.strip(),
                   root=toy)
    out = json.loads(proc.stdout)
    assert out["closed"] and out["bindings_released"] >= 1
    sc = Sidecar(toy)
    try:
        assert sc.state_get(session, "active_slice") is None
        assert sc.state_get("__default__", "active_slice") is None
    finally:
        sc.close()


# ---------------------------------------------------------------- #20
def test_acceptance_runner_prefers_project_venv(toy):
    from importlib.machinery import SourceFileLoader
    harness_cli = SourceFileLoader(
        "harness_cli", str((toy / "..").resolve() )).path  # noqa: unused trick
    # import the CLI module directly for the helper
    import importlib.util
    from conftest import PLUGIN_ROOT
    spec = importlib.util.spec_from_loader("hbin", None)
    src = (PLUGIN_ROOT / "bin" / "harness").read_text()
    module = importlib.util.module_from_spec(spec)
    module.__dict__["__file__"] = str(PLUGIN_ROOT / "bin" / "harness")
    exec(compile(src, str(PLUGIN_ROOT / "bin" / "harness"), "exec"),
         module.__dict__)
    cfg = load_config(toy)
    # no venv -> engine interpreter
    assert module._acceptance_python(toy, cfg) == sys.executable
    # project venv wins
    venv_py = toy / ".venv" / "bin" / "python"
    venv_py.parent.mkdir(parents=True)
    os.symlink(sys.executable, venv_py)
    assert module._acceptance_python(toy, cfg) == str(venv_py)
    # explicit config wins over venv
    cfg["gates"]["acceptance_python"] = "/custom/python"
    assert module._acceptance_python(toy, cfg) == "/custom/python"
    # a configured-but-missing interpreter fails LOUD at close
    ok, msg = module._acceptance_green(
        toy, {"acceptance": ["tests/slices/042_orders.py"]}, cfg)
    assert not ok and "does not exist" in msg


# ------------------------------------------------- re-audit remaining #1
def test_decisions_block_includes_rows_from_loaded_adrs(toy):
    """A row whose domain matches nothing declared still joins the curated
    decisions block when its authoring ADR is loaded as guidance for the
    slice — the block must be a superset of what the builder can already see
    in that ADR's frontmatter."""
    rows = read_jsonl(toy / ".harness" / "decisions.jsonl")
    rows.append({"id": "D-070", "domain": "api",  # 'api' ∉ domain_keys
                 "question": "Input validation style?",
                 "answer": "Reject at the edge; never sanitize silently.",
                 "adr_ref": "adr/007-telemetry.md",  # loaded via config's guidance
                 "origin": "phase0", "created": "2026-01-01T00:00:00+00:00"})
    rows.append({"id": "D-071", "domain": "api",
                 "question": "Rate limiting?", "answer": "Token bucket.",
                 "adr_ref": "adr/999-unloaded.md",  # NOT loaded for this slice
                 "origin": "phase0", "created": "2026-01-01T00:00:00+00:00"})
    write_jsonl(toy / ".harness" / "decisions.jsonl", rows)
    from engine.resolver import resolve
    out = resolve(toy, "slice-042", load_config(toy))
    assert "decision:D-070" in out["context_loaded"], \
        "rows from loaded ADRs must join the decisions block"
    assert "decision:D-071" not in out["context_loaded"], \
        "rows from unloaded ADRs must not leak in"


# ------------------------------------------------- autonomy profile
def test_init_autonomy_writes_permission_profile(tmp_path):
    target = tmp_path / "fresh"
    target.mkdir()
    (target / "app.py").write_text("x = 1\n")
    proc = run_cli("init", "--autonomy", root=target)
    assert proc.returncode == 0, proc.stderr
    settings = json.loads((target / ".claude" / "settings.json").read_text())
    perms = settings["permissions"]
    assert perms["defaultMode"] == "acceptEdits"
    assert any("bin/harness:*" in r for r in perms["allow"])
    assert "{{HARNESS_BIN}}" not in json.dumps(settings)  # substituted
    assert any(r.startswith("Bash(pytest") for r in perms["allow"])
    assert "Bash(git push:*)" in perms["deny"]  # nothing leaves the machine

    # re-run on existing substrate: adds/keeps profile, never clobbers
    (target / ".claude" / "settings.json").write_text('{"permissions": {}}')
    proc = run_cli("init", "--autonomy", root=target)
    assert proc.returncode == 0
    assert json.loads((target / ".claude" / "settings.json").read_text()) == \
        {"permissions": {}}  # existing file untouched
    assert "not touched" in proc.stdout


def test_init_without_autonomy_writes_no_settings(tmp_path):
    target = tmp_path / "fresh2"
    target.mkdir()
    run_cli("init", root=target)
    assert not (target / ".claude" / "settings.json").exists()


# ---------------------------------------------------------------- #16
def test_generated_contract_mode_exempts_coverage(toy):
    (toy / "adr" / "012-genapi.md").write_text(
        '---\nid: "012"\nstatus: accepted\ncontract_mode: generated\n'
        'api_surface:\n  - "GET /metrics"\n---\nbody\n')
    report = compile_substrate(toy)
    assert not any("/metrics" in g for g in report["contract_gaps"])
    result = author_gate(toy)
    assert not any("GET /metrics" in g for g in result["gaps"]), result["gaps"]


# ---------------------------------------------------------------- #17
def test_custom_domain_preserved_and_gate_checks_coverage(toy):
    (toy / "adr" / "013-data.md").write_text(
        '---\nid: "013"\nstatus: accepted\nabstractions:\n'
        '  - id: warehouse\n    kind: data\n---\nbody\n')
    compile_substrate(toy)
    reg = {e["id"]: e for e in read_jsonl(toy / ".harness" / "registry.jsonl")}
    assert reg["warehouse"]["kind"] == "other"
    assert reg["warehouse"]["domain"] == "data"
    # coverage hole closed: 'data' now demands a decision row
    result = author_gate(toy)
    assert any("'data'" in g for g in result["gaps"])
    rows = read_jsonl(toy / ".harness" / "decisions.jsonl")
    rows.append({"id": "D-200", "domain": "data", "question": "q", "answer": "a",
                 "adr_ref": None, "origin": "phase0",
                 "created": "2026-01-01T00:00:00+00:00"})
    write_jsonl(toy / ".harness" / "decisions.jsonl", rows)
    result = author_gate(toy)
    assert not any("'data'" in g for g in result["gaps"])
