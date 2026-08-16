"""ADR-002 / D-007: repo-local `gates.extra` gates + `registry.kinds_extra`.

Both keys are optional: absent, the engine must behave exactly as 0.7.1. A
listed gate that cannot be loaded is a loud blocking finding, never a silent
skip, and the builtin pack keeps running regardless.
"""
import json
import os
import shutil
from pathlib import Path

from conftest import loaded_context, make_event, run_cli
from engine import load_config, read_jsonl, write_jsonl
from engine.compiler import compile_substrate
from engine.events import handle_event
from engine.gates import GateContext, all_gates, gates_for_event
from engine.gates.extra import load_extra_gates, run_gate
from engine.registry import REGISTRY_KINDS, registry_kinds
from engine.schema import validate_substrate

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "extra_gates"
BUILTIN_IDS = [f"G{i}" for i in range(1, 9)]

ADR_008 = '''---
id: "008"
status: accepted
domains: [package]
supersedes: []
decision_table_rows:
  - id: D-050
    domain: package
    question: "How is a distribution laid out?"
    answer: "One distribution per subpackage; never ship the namespace init."
abstractions:
  - id: kente-core
    kind: package
    source: core.py
    section: s1
api_surface: []
---

# ADR-008: Packages

## Status

Accepted.

## Context

<!-- #s1 -->
One distribution per subpackage.

## Decision

PEP 420 namespace packages.

## Consequences

Lockstep versioning.

## Considered Alternatives

A single fat distribution.

## Implementation

Ship each subpackage separately.
'''

PRE_ONLY_GATE = '''"""A gate that only declares pre_change."""

GATE = {"id": "K7", "rule_ref": "adr:002", "preferred": ["pre_change"],
        "fallback": []}


def run(ctx):
    """Always fires, so its absence in CI output is meaningful."""
    from engine.events import make_finding
    return [make_finding("PRE_ONLY_RAN", "adr:002", "pre-only gate ran",
                         severity="block", key="pre-only")]
'''

SHAPELESS_GATE = '''"""A gate whose GATE dict is missing the required id."""

GATE = {"preferred": ["pre_change"]}


def run(ctx):
    return []
'''

# A gate that escapes the repo must never execute: it drops this marker.
ESCAPED_GATE = '''"""A gate that must never be imported."""
import pathlib

pathlib.Path(__file__).with_name("EXECUTED").write_text("x")

GATE = {"id": "KX", "rule_ref": "adr:002", "preferred": ["pre_change"],
        "fallback": []}


def run(ctx):
    return []
'''

NO_RULE_REF_GATE = '''"""A gate emitting a blocking finding with no rule_ref."""

GATE = {"id": "K2", "rule_ref": "adr:002",
        "preferred": ["pre_change", "unit_complete"], "fallback": []}


def run(ctx):
    return [{"finding_id": "F-nope", "layer": 0, "severity": "block",
             "code": "SLOPPY", "rule_ref": "", "message": "no rule_ref"}]
'''

NO_SEVERITY_GATE = '''"""A gate emitting a finding with no severity field."""

GATE = {"id": "K3", "rule_ref": "adr:002",
        "preferred": ["pre_change", "unit_complete"], "fallback": []}


def run(ctx):
    return [{"finding_id": "F-nope", "layer": 0, "code": "SLOPPY",
             "rule_ref": "adr:002", "message": "no severity"}]
'''

RAISING_GATE = '''"""A gate that raises while running."""

GATE = {"id": "K4", "rule_ref": "adr:002", "preferred": ["pre_change"],
        "fallback": []}


def run(ctx):
    raise ZeroDivisionError("boom in run")
'''

NON_LIST_GATE = '''"""A gate that returns something that is not a list."""

GATE = {"id": "K5", "rule_ref": "adr:002", "preferred": ["pre_change"],
        "fallback": []}


def run(ctx):
    return {"not": "a list"}
'''

COLLIDING_GATE = '''"""A gate claiming a builtin gate id."""

GATE = {"id": "G3", "rule_ref": "adr:002", "preferred": ["pre_change"],
        "fallback": []}


def run(ctx):
    return []
'''

UNKNOWN_EVENT_GATE = '''"""A gate naming an event the engine does not have."""

GATE = {"id": "K6", "rule_ref": "adr:002", "preferred": ["pre_commit"],
        "fallback": []}


def run(ctx):
    return []
'''


# ------------------------------------------------------------------ helpers
def _install(toy, name):
    """Copy a fixture gate into the toy repo; return its config entry."""
    d = toy / ".harness" / "gates"
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / name, d / name)
    return f".harness/gates/{name}"


def _write_gate(toy, name, text):
    d = toy / ".harness" / "gates"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text)
    return f".harness/gates/{name}"


def _configure(toy, extra=None, kinds_extra=None):
    """Set gates.extra / registry.kinds_extra on the toy config."""
    import yaml
    cfg = toy / ".harness" / "config.yaml"
    doc = yaml.safe_load(cfg.read_text())
    if extra is not None:
        doc.setdefault("gates", {})["extra"] = list(extra)
    if kinds_extra is not None:
        doc.setdefault("registry", {})["kinds_extra"] = list(kinds_extra)
    cfg.write_text(yaml.safe_dump(doc, sort_keys=False))
    return load_config(toy)


def _close_slice(toy, predicted):
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    for r in rows:
        r["status"] = "closed"
        r["predicted_files"] = list(predicted)
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)


def _verify(toy):
    proc = run_cli("verify", root=toy)
    return proc.returncode, json.loads(proc.stdout)


def _codes(out):
    return {f["code"] for f in out["findings"]}


def _ctx(toy, config, event="pre_change", files=("orders.py",)):
    """A GateContext for calling a single gate directly."""
    from engine.gates.extra import _NullSidecar
    return GateContext(toy, make_event(event, files=list(files)), config,
                       _NullSidecar())


# ------------------------------------------------------------ compatibility
def test_absent_keys_keep_previous_behaviour(toy):
    assert [g.GATE["id"] for g in all_gates()] == BUILTIN_IDS
    config = load_config(toy)
    assert [g.GATE["id"] for g in all_gates(root=toy, config=config)] == BUILTIN_IDS
    assert [g.GATE["id"] for g in gates_for_event("pre_change")] == \
        [g.GATE["id"] for g in gates_for_event("pre_change", root=toy, config=config)]
    assert load_extra_gates(toy, config) == ([], [])
    assert registry_kinds(None) == set(REGISTRY_KINDS)
    assert registry_kinds({}) == set(REGISTRY_KINDS)


# ------------------------------------------------------------------- loading
def test_good_gate_is_selected_for_its_declared_events(toy):
    config = _configure(toy, extra=[_install(toy, "good_gate.py")])
    gates, errors = load_extra_gates(toy, config)
    assert errors == []
    assert [g.GATE["id"] for g in gates] == ["K1"]
    assert "K1" in [g.GATE["id"] for g in
                    gates_for_event("pre_change", root=toy, config=config)]
    assert "K1" not in [g.GATE["id"] for g in
                        gates_for_event("pre_context", root=toy, config=config)]


def test_module_attr_entry_form_loads(toy):
    config = _configure(toy, extra=["fixtures.extra_gates.good_gate:GATE"])
    gates, errors = load_extra_gates(toy, config)
    assert errors == []
    assert [g.GATE["id"] for g in gates] == ["K1"]


def test_good_gate_blocks_a_namespace_capturing_pre_change(toy):
    _configure(toy, extra=[_install(toy, "good_gate.py")])
    loaded_context(toy, session="k1")
    v = handle_event(make_event("pre_change", session="k1",
                                files=["src/kente/__init__.py"]), toy)
    assert v["verdict"] == "block"
    hits = [f for f in v["findings"] if f["code"] == "NAMESPACE_CAPTURE"]
    assert hits, v["findings"]
    assert hits[0]["rule_ref"] == "adr:002"
    assert hits[0]["severity"] == "block"


# ------------------------------------------------------------- fail closed
def test_bad_gate_is_one_loud_blocking_finding(toy):
    bad = _install(toy, "bad_gate.py")
    good = _install(toy, "good_gate.py")
    config = _configure(toy, extra=[bad, good])

    gates, errors = load_extra_gates(toy, config)
    assert [g.GATE["id"] for g in gates] == ["K1"]  # the good gate still loads
    assert len(errors) == 1
    err = errors[0]
    assert err["code"] == "EXTRA_GATE_LOAD_ERROR"
    assert err["severity"] == "block"
    assert err["rule_ref"] == "adr:002"
    assert bad in err["message"]
    assert "deliberate import failure" in err["message"]

    v = handle_event(make_event("pre_change", session="kbad",
                                files=["orders.py"]), toy)
    assert v["verdict"] == "block"
    assert len([f for f in v["findings"]
                if f["code"] == "EXTRA_GATE_LOAD_ERROR"]) == 1
    builtin_refs = {f"gate:G{i}" for i in range(1, 9)}
    assert {f["rule_ref"] for f in v["findings"]} & builtin_refs


def test_missing_entry_file_is_a_load_error(toy):
    config = _configure(toy, extra=[".harness/gates/nope.py"])
    gates, errors = load_extra_gates(toy, config)
    assert gates == []
    assert len(errors) == 1
    assert ".harness/gates/nope.py" in errors[0]["message"]
    assert errors[0]["code"] == "EXTRA_GATE_LOAD_ERROR"


def test_gate_missing_required_declaration_fields_is_a_load_error(toy):
    entry = _write_gate(toy, "shapeless.py", SHAPELESS_GATE)
    config = _configure(toy, extra=[entry])
    gates, errors = load_extra_gates(toy, config)
    assert gates == []
    assert errors[0]["code"] == "EXTRA_GATE_LOAD_ERROR"
    assert "id" in errors[0]["message"]


# ------------------------------------------------------------------ verify
def test_verify_fails_on_a_bad_extra_gate_entry(toy):
    _configure(toy, extra=[_install(toy, "bad_gate.py")])
    code, out = _verify(toy)
    assert code == 1
    assert "EXTRA_GATE_LOAD_ERROR" in _codes(out)


def test_verify_runs_extra_gates_over_closed_slices(toy):
    (toy / "src" / "kente").mkdir(parents=True)
    (toy / "src" / "kente" / "__init__.py").write_text("")
    _close_slice(toy, ["src/kente/__init__.py"])
    _configure(toy, extra=[_install(toy, "good_gate.py")])
    code, out = _verify(toy)
    assert code == 1
    assert "NAMESPACE_CAPTURE" in _codes(out)


def test_verify_skips_pre_change_only_extra_gates(toy):
    _close_slice(toy, ["orders.py"])
    entry = _write_gate(toy, "preonly.py", PRE_ONLY_GATE)
    _configure(toy, extra=[entry])
    _code, out = _verify(toy)
    assert "PRE_ONLY_RAN" not in _codes(out)
    assert "EXTRA_GATE_LOAD_ERROR" not in _codes(out)


# --------------------------------------------------------- registry kinds
def test_registry_kinds_extra_widens_the_enum():
    kinds = registry_kinds({"registry": {"kinds_extra": ["package"]}})
    assert "package" in kinds
    assert set(REGISTRY_KINDS) <= kinds


def test_compile_keeps_an_extra_kind(toy):
    _configure(toy, kinds_extra=["package"])
    (toy / "core.py").write_text('"""Core."""\n')
    (toy / "adr" / "008-packages.md").write_text(ADR_008)
    report = compile_substrate(toy)
    entries = {e["id"]: e for e in read_jsonl(toy / ".harness" / "registry.jsonl")}
    assert entries["kente-core"]["kind"] == "package"
    assert not [w for w in report["warnings"] if "kente-core" in w]
    assert validate_substrate(toy) == []


def test_compile_still_coerces_an_unknown_kind(toy):
    (toy / "core.py").write_text('"""Core."""\n')
    (toy / "adr" / "008-packages.md").write_text(ADR_008)
    report = compile_substrate(toy)
    entries = {e["id"]: e for e in read_jsonl(toy / ".harness" / "registry.jsonl")}
    assert entries["kente-core"]["kind"] == "other"
    assert [w for w in report["warnings"] if "kente-core" in w]


# ------------------------------------------------------------- containment
def _outside_gate(tmp_path, name="evil.py"):
    """Write a repo-escaping gate module; return (path, marker path)."""
    outside = tmp_path / "outside"
    outside.mkdir(exist_ok=True)
    (outside / name).write_text(ESCAPED_GATE)
    return outside / name, outside / "EXECUTED"


def _assert_rejected_uncontained(toy, entry, marker):
    gates, errors = load_extra_gates(toy, _configure(toy, extra=[entry]))
    assert gates == []
    assert len(errors) == 1
    err = errors[0]
    assert err["code"] == "EXTRA_GATE_LOAD_ERROR"
    assert err["severity"] == "block" and err["rule_ref"] == "adr:002"
    assert entry in err["message"]
    assert "must be repo-relative and inside the repo" in err["message"]
    assert not marker.exists(), "an uncontained gate must never execute"


def test_traversal_path_entry_is_rejected(toy, tmp_path):
    """`../` out of the repo is arbitrary code execution, not a gate."""
    _path, marker = _outside_gate(tmp_path)
    rel = os.path.relpath(_path, toy)
    assert rel.startswith("..")
    _assert_rejected_uncontained(toy, rel, marker)


def test_absolute_path_entry_is_rejected(toy, tmp_path):
    """Entries are repo-relative; the absolute form is not accepted at all."""
    path, marker = _outside_gate(tmp_path, "abs.py")
    _assert_rejected_uncontained(toy, str(path), marker)


def test_absolute_path_inside_the_repo_is_still_rejected(toy):
    """Even a contained absolute path is rejected — the form is gone."""
    entry_rel = _install(toy, "good_gate.py")
    absolute = str(toy / entry_rel)
    gates, errors = load_extra_gates(toy, _configure(toy, extra=[absolute]))
    assert gates == []
    assert errors[0]["code"] == "EXTRA_GATE_LOAD_ERROR"
    assert "must be repo-relative and inside the repo" in errors[0]["message"]


def test_symlink_escaping_the_repo_is_rejected(toy, tmp_path):
    """Containment is checked after resolution, so symlinks cannot escape."""
    path, marker = _outside_gate(tmp_path, "linked.py")
    d = toy / ".harness" / "gates"
    d.mkdir(parents=True, exist_ok=True)
    (d / "link.py").symlink_to(path)
    _assert_rejected_uncontained(toy, ".harness/gates/link.py", marker)


# ------------------------------------------------------- finding validation
def test_block_without_rule_ref_becomes_a_run_error(toy):
    """D-003/D-007: a blocking finding with no rule_ref never reaches a
    verdict — not even from a repo-local gate."""
    entry = _write_gate(toy, "norule.py", NO_RULE_REF_GATE)
    _configure(toy, extra=[entry])
    v = handle_event(make_event("pre_change", session="knr",
                                files=["orders.py"]), toy)
    codes = {f["code"] for f in v["findings"]}
    assert "SLOPPY" not in codes
    hits = [f for f in v["findings"] if f["code"] == "EXTRA_GATE_RUN_ERROR"]
    assert len(hits) == 1
    assert entry in hits[0]["message"]
    assert hits[0]["severity"] == "block" and hits[0]["rule_ref"] == "adr:002"
    assert "rule_ref" in hits[0]["message"]


def test_verify_rejects_a_rule_ref_less_block_from_an_extra_gate(toy):
    _close_slice(toy, ["orders.py"])
    entry = _write_gate(toy, "norule.py", NO_RULE_REF_GATE)
    _configure(toy, extra=[entry])
    code, out = _verify(toy)
    assert code == 1
    assert "SLOPPY" not in _codes(out)
    hits = [f for f in out["findings"] if f["code"] == "EXTRA_GATE_RUN_ERROR"]
    assert hits and entry in hits[0]["message"]


def test_finding_without_severity_does_not_crash_verify(toy):
    """A missing `severity` used to KeyError out of `harness verify`."""
    _close_slice(toy, ["orders.py"])
    entry = _write_gate(toy, "nosev.py", NO_SEVERITY_GATE)
    _configure(toy, extra=[entry])
    code, out = _verify(toy)
    assert code == 1
    hits = [f for f in out["findings"] if f["code"] == "EXTRA_GATE_RUN_ERROR"]
    assert hits and entry in hits[0]["message"]
    assert all("severity" in f for f in out["findings"])


# -------------------------------------------------------------- run errors
def test_gate_raising_in_run_is_a_run_error_with_a_frame(toy):
    entry = _write_gate(toy, "raiser.py", RAISING_GATE)
    _configure(toy, extra=[entry])
    v = handle_event(make_event("pre_change", session="kraise",
                                files=["orders.py"]), toy)
    hits = [f for f in v["findings"] if f["code"] == "EXTRA_GATE_RUN_ERROR"]
    assert len(hits) == 1
    msg = hits[0]["message"]
    assert entry in msg and "boom in run" in msg
    assert "raiser.py:" in msg, msg   # last traceback frame, file:line
    builtin_refs = {f"gate:G{i}" for i in range(1, 9)}
    assert {f["rule_ref"] for f in v["findings"]} & builtin_refs


def test_gate_returning_a_non_list_is_a_run_error(toy):
    entry = _write_gate(toy, "nonlist.py", NON_LIST_GATE)
    config = _configure(toy, extra=[entry])
    gates, errors = load_extra_gates(toy, config)
    assert errors == [] and len(gates) == 1
    out = run_gate(gates[0], _ctx(toy, config))
    assert len(out) == 1 and out[0]["code"] == "EXTRA_GATE_RUN_ERROR"
    assert entry in out[0]["message"] and "dict" in out[0]["message"]


# ------------------------------------------------------ declaration checks
def test_id_colliding_with_a_builtin_gate_is_a_load_error(toy):
    entry = _write_gate(toy, "collide.py", COLLIDING_GATE)
    gates, errors = load_extra_gates(toy, _configure(toy, extra=[entry]),
                                     reserved_ids={"G3"})
    assert gates == []
    assert errors[0]["code"] == "EXTRA_GATE_LOAD_ERROR"
    assert "G3" in errors[0]["message"]


def test_id_colliding_with_a_builtin_is_caught_on_dispatch(toy):
    """all_gates()/run_gates supply the builtin ids themselves."""
    entry = _write_gate(toy, "collide.py", COLLIDING_GATE)
    config = _configure(toy, extra=[entry])
    ids = [g.GATE["id"] for g in all_gates(root=toy, config=config)]
    assert ids == BUILTIN_IDS
    v = handle_event(make_event("pre_change", session="kcol",
                                files=["orders.py"]), toy)
    assert "EXTRA_GATE_LOAD_ERROR" in {f["code"] for f in v["findings"]}


def test_unknown_event_name_is_a_load_error(toy):
    entry = _write_gate(toy, "unknownevent.py", UNKNOWN_EVENT_GATE)
    gates, errors = load_extra_gates(toy, _configure(toy, extra=[entry]))
    assert gates == []
    assert errors[0]["code"] == "EXTRA_GATE_LOAD_ERROR"
    assert "pre_commit" in errors[0]["message"]


# ---------------------------------------------------------- verify hygiene
def test_verify_ignores_escaping_declared_paths_on_a_closed_slice(toy):
    """A backlog row naming `../x` or an absolute glob must not crash CI."""
    (toy / "src" / "kente").mkdir(parents=True)
    (toy / "src" / "kente" / "__init__.py").write_text("")
    _close_slice(toy, ["../outside/x.py", "/etc/*.conf",
                       "src/kente/__init__.py"])
    _configure(toy, extra=[_install(toy, "good_gate.py")])
    code, out = _verify(toy)
    assert code == 1
    assert "NAMESPACE_CAPTURE" in _codes(out)   # the contained path still runs


# --------------------------------------------------------- registry kinds
def test_kinds_extra_must_be_strings():
    import pytest

    from engine import HarnessError
    with pytest.raises(HarnessError):
        registry_kinds({"registry": {"kinds_extra": ["package", 7]}})
