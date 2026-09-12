"""Regression coverage for the September behavior audit."""
import json

from conftest import git, make_event, run_cli
from engine import read_jsonl, write_jsonl
from engine.events import Sidecar, handle_event
from engine.gates.g6_drift import acknowledge
from engine.graph import load_edges, uses_vs_declares, provenance

GOOD = "def create_order(sku: str) -> dict:\n    return {'sku': sku}\n"


def bind(toy, deps=None, session="audit"):
    if deps is not None:
        rows = read_jsonl(toy / ".harness/backlog.jsonl")
        rows[0]["declares_dep"] = deps
        write_jsonl(toy / ".harness/backlog.jsonl", rows)
    p = run_cli("slice", "--slice", "slice-042", "--session", session, root=toy)
    assert p.returncode == 0, p.stdout + p.stderr


def event(toy, kind="unit_complete", files=None, sid="slice-042", session="audit"):
    return handle_event(make_event(kind, session=session, slice_id=sid, files=files), toy)


def changed(toy, text):
    (toy / "orders.py").write_text(text)
    event(toy, "post_change", ["orders.py"])
    return event(toy)


def commit(toy):
    assert git(toy, "add", "-A").returncode == 0
    p = git(toy, "commit", "-qm", "slice work")
    assert p.returncode == 0, p.stderr


def close(toy):
    p = run_cli("close-slice", "--slice", "slice-042", "--session", "audit",
                "--commit", "HEAD", root=toy)
    return p, json.loads(p.stdout)


def test_removing_import_retires_current_use_but_preserves_history(toy):
    bind(toy, ["config"])
    changed(toy, "import telemetry\n" + GOOD)
    assert uses_vs_declares(toy, "slice-042")["unresolved"]
    changed(toy, GOOD)
    assert uses_vs_declares(toy, "slice-042")["unresolved"] == []
    assert any(e["type"] == "uses" for e in load_edges(toy))


def test_deleting_source_retires_current_use(toy):
    bind(toy, ["config"])
    changed(toy, "import telemetry\n" + GOOD)
    (toy / "orders.py").unlink()
    event(toy, "post_change", ["orders.py"])
    event(toy)
    assert uses_vs_declares(toy, "slice-042")["uses"] == []


def test_shared_session_cannot_attribute_other_slice_touches(toy):
    rows = read_jsonl(toy / ".harness/backlog.jsonl")
    rows.append({**rows[0], "id": "slice-B", "declares_dep": [], "predicted_files": ["b.py"]})
    write_jsonl(toy / ".harness/backlog.jsonl", rows)
    bind(toy)
    changed(toy, "import telemetry\n" + GOOD)
    assert run_cli("slice", "--slice", "slice-B", "--session", "audit", root=toy).returncode == 0
    event(toy, sid="slice-B")
    assert not [e for e in load_edges(toy) if e["from"] == "slice:slice-B"
                and e["type"] in ("touches", "uses")]


def test_drift_ack_does_not_override_dependency_conformance(toy):
    bind(toy, ["config"])
    changed(toy, "import telemetry\n" + GOOD)
    acknowledge(toy, "slice-042", "telemetry", "interface change only")
    assert "UNDECLARED_USE" in [f["code"] for f in event(toy)["findings"]]
    assert uses_vs_declares(toy, "slice-042")["unresolved"] == ["module:telemetry"]


def test_lost_sidecar_recovers_original_drift_baseline(toy):
    bind(toy)
    p = toy / "telemetry.py"
    p.write_text(p.read_text() + "\n\ndef flush():\n    return None\n")
    event(toy, "post_change", ["telemetry.py"])
    assert "INTERFACE_DRIFT" in [f["code"] for f in event(toy)["findings"]]
    for suffix in ("", "-wal", "-shm"):
        (toy / ".harness" / ("sidecar.db" + suffix)).unlink(missing_ok=True)
    assert "INTERFACE_DRIFT" in [f["code"] for f in event(toy)["findings"]]


def test_close_rejects_uncommitted_acceptance_fix(toy):
    bind(toy)
    changed(toy, "def create_order(sku):\n    raise ValueError('broken')\n")
    commit(toy)
    changed(toy, GOOD)
    p, out = close(toy)
    assert p.returncode == 1 and out["closed"] is False
    assert "commit" in out["reason"].lower()
    assert read_jsonl(toy / ".harness/backlog.jsonl")[0]["status"] != "closed"


def test_close_checks_new_import_without_hook_events(toy):
    bind(toy, ["config"])
    (toy / "orders.py").write_text("import telemetry\n" + GOOD)
    commit(toy)
    p, out = close(toy)
    assert p.returncode == 1 and out["closed"] is False
    assert "UNDECLARED_USE" in json.dumps(out) or "module:telemetry" in json.dumps(out)


def test_failed_substrate_commit_is_retryable(toy):
    bind(toy)
    changed(toy, GOOD)
    commit(toy)
    hook = toy / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    p, out = close(toy)
    assert p.returncode == 1 and out["closed"] is False
    from engine.telemetry import aggregate
    assert aggregate(toy)["outcome_counts"].get("slice_closed", 0) == 0
    indexed = [json.loads(line) for line in git(toy, "show", ":.harness/backlog.jsonl").stdout.splitlines()]
    assert indexed[0]["status"] != "closed"
    orders = next(e for e in read_jsonl(toy / ".harness/registry.jsonl") if e["id"] == "orders")
    assert orders["status"] == "planned"
    assert not [e for e in load_edges(toy) if e["type"] == "produced_by"]
    hook.unlink()
    p, out = close(toy)
    assert p.returncode == 0 and out["closed"] and out["substrate_commit"]
    committed = [json.loads(s) for s in git(toy, "show", "HEAD:.harness/backlog.jsonl").stdout.splitlines()]
    assert committed[0]["status"] == "closed"


def test_close_checks_hookless_non_goal_even_when_declared(toy):
    bind(toy)
    rows = read_jsonl(toy / ".harness/backlog.jsonl")
    rows[0]["predicted_files"].append("legacy/export.py")
    write_jsonl(toy / ".harness/backlog.jsonl", rows)
    (toy / "legacy").mkdir()
    (toy / "legacy/export.py").write_text("value = 1\n")
    (toy / "orders.py").write_text(GOOD)
    commit(toy)
    p, out = close(toy)
    assert p.returncode == 1 and "NON_GOAL_VIOLATION" in json.dumps(out)


def test_close_recovers_crash_after_substrate_commit(toy, monkeypatch):
    import pytest
    import engine.cli.closure_state as state
    from argparse import Namespace
    from engine.cli.ceremony import _close_ceremony
    bind(toy)
    changed(toy, GOOD)
    commit(toy)
    finish = state.finish_closure
    def interrupted(*args):
        raise KeyboardInterrupt("simulated process death")
    monkeypatch.setattr(state, "finish_closure", interrupted)
    with pytest.raises(KeyboardInterrupt):
        _close_ceremony(Namespace(root=str(toy), slice="slice-042", session="audit", commit="HEAD"))
    head = git(toy, "rev-parse", "HEAD").stdout
    monkeypatch.setattr(state, "finish_closure", finish)
    p, out = close(toy)
    assert p.returncode == 0 and out["closed"] and out["recovered"]
    assert git(toy, "rev-parse", "HEAD").stdout == head
    assert not state.journal_path(toy, "slice-042").exists()


def test_close_records_module_revision_and_governing_decisions(toy):
    bind(toy)
    changed(toy, GOOD)
    # Editing an existing abstraction must have provenance too.
    p = toy / "telemetry.py"
    p.write_text(p.read_text() + "\n# implementation detail\n")
    event(toy, "post_change", ["telemetry.py"])
    commit(toy)
    revision = git(toy, "rev-parse", "HEAD").stdout.strip()
    proc, out = close(toy)
    assert proc.returncode == 0, out
    for module in ("orders", "telemetry"):
        history = provenance(toy, module)
        assert revision in history["commits"]
        assert "decision:D-041" in history["decisions"]
    # CI must detect missing graph evidence, not accept an empty ledger.
    write_jsonl(toy / ".harness/edges.jsonl", [])
    assert "INCOMPLETE_GRAPH_PROVENANCE" in run_cli("verify", root=toy).stdout


def test_legacy_graph_repair_uses_recorded_facts_only(toy):
    from engine.graph import write_note, repair_legacy_provenance
    rows = read_jsonl(toy / ".harness/backlog.jsonl")
    rows[0]["status"] = "closed"
    write_jsonl(toy / ".harness/backlog.jsonl", rows)
    revision = git(toy, "rev-parse", "HEAD").stdout.strip()
    write_note(toy, revision, {"slice_id": "slice-042", "modules_touched": ["telemetry.py"],
                               "registry_used": ["telemetry"]})
    report = repair_legacy_provenance(toy)
    assert report["edges_added"] and report["slices"] == ["slice-042"]
    assert provenance(toy, "telemetry")["commits"] == [revision]
    assert provenance(toy, "telemetry")["decisions"] == []
    assert not {"dependency_snapshot", "satisfies"} & {e["type"] for e in load_edges(toy)}
    assert repair_legacy_provenance(toy)["edges_added"] == 0
