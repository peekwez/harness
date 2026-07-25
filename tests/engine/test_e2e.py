"""C8/M4 acceptance on the toy repo: block -> inject -> pass; Stop
regenerates shadows + edges; session cycling; the full close ceremony;
backlog splitting; init idempotence."""
import json

from conftest import git, loaded_context, make_event, run_cli
from engine.events import handle_event


def test_toy_repo_end_to_end_block_then_pass(toy):
    # 1. An agent editing a file without context is blocked with a pointer.
    v = handle_event(make_event("pre_change", session="e2e",
                                files=["orders.py"]), toy)
    assert v["verdict"] == "block"
    pointers = [i for f in v["findings"] for i in f["inject"]]
    assert pointers and any("shadow" in p for p in pointers)

    # 2. After Phase-1 injection the same edit passes.
    start = loaded_context(toy, session="e2e")
    assert start["injections"], "Phase 1 must inject"
    v2 = handle_event(make_event("pre_change", session="e2e",
                                 files=["orders.py"]), toy)
    assert v2["verdict"] == "allow", v2["findings"]

    # 3. Write the file; Stop regenerates shadows and writes edges.
    (toy / "orders.py").write_text(
        "import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
        "    telemetry.emit_span('create_order', {'sku': sku})\n"
        "    return {'sku': sku}\n")
    handle_event(make_event("post_change", session="e2e",
                            files=["orders.py"]), toy)
    handle_event(make_event("unit_complete", session="e2e"), toy)
    assert (toy / ".harness" / "shadows" / "orders.py.json").exists()
    from engine.graph import load_edges
    edges = load_edges(toy)
    assert any(e["type"] == "touches" and e["to"] == "file:orders.py"
               for e in edges)
    assert any(e["type"] == "uses" and e["to"] == "module:telemetry"
               for e in edges)


def test_session_cycling_resumes_from_substrate_alone(toy):
    """Kill the session mid-slice, resume with a fresh session, complete."""
    loaded_context(toy, session="dying")
    (toy / "orders.py").write_text("import telemetry\n\ndef create_order(s):\n"
                                   "    return telemetry.emit_span('o', {})\n")
    handle_event(make_event("post_change", session="dying",
                            files=["orders.py"]), toy)
    run_cli("memory", "write", "--slice", "slice-042", "--kind", "attempt",
            "--content", "tried dataclass orders",
            "--approach", "dataclass", "--outcome", "abandoned",
            "--why", "dict is the decided row", root=toy)
    # session dies here. New session: resolver rebuilds everything.
    fresh = loaded_context(toy, session="fresh")
    assert fresh["injections"]
    v = handle_event(make_event("pre_change", session="fresh",
                                files=["orders.py"]), toy)
    assert v["verdict"] == "allow", v["findings"]
    # the attempt memory survived the cycle in substrate
    from engine import memory
    entries = memory.read_session(toy, "slice-042")
    assert any(e["kind"] == "attempt" for e in entries)


def test_full_close_ceremony(toy):
    session = "close"
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
    git(toy, "commit", "-qm", "slice-042: orders service")
    head = git(toy, "rev-parse", "HEAD").stdout.strip()

    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", head, root=toy)
    out = json.loads(proc.stdout)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert out["closed"] and out["note_written"]
    assert "orders" in out["registry_flipped"]

    from engine import read_jsonl
    backlog = read_jsonl(toy / ".harness" / "backlog.jsonl")
    assert backlog[0]["status"] == "closed"
    registry = {e["id"]: e for e in read_jsonl(toy / ".harness" / "registry.jsonl")}
    assert registry["orders"]["status"] == "built"
    notes = git(toy, "notes", "--ref=refs/notes/harness", "list").stdout
    assert notes.strip(), "git note must exist"
    assert not (toy / ".harness" / "memory" / "session" / "slice-042.jsonl").exists()

    # verify stays green after the ceremony (uses ⊆ declares reconciled)
    proc = run_cli("verify", root=toy)
    assert proc.returncode == 0, proc.stdout


GOOD_ORDERS = ("import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
               "    telemetry.emit_span('create_order', {'sku': sku})\n"
               "    return {'sku': sku}\n")


def test_close_blocked_on_undeclared_use(toy):
    session = "close-bad"
    run_cli("slice", "--slice", "slice-042", "--session", session, root=toy)
    loaded_context(toy, session=session)
    (toy / "orders.py").write_text(GOOD_ORDERS)  # acceptance green
    from engine.graph import append_edge
    append_edge(toy, "uses", "slice:slice-042", "module:ghost")
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   root=toy)
    assert proc.returncode == 1
    assert "ghost" in proc.stdout


def test_close_blocked_on_red_acceptance(toy):
    """§7.5 'acceptance green' is engine-enforced, not skill prose (§1.4)."""
    session = "close-red"
    run_cli("slice", "--slice", "slice-042", "--session", session, root=toy)
    loaded_context(toy, session=session)
    # orders.py never written -> the acceptance test cannot pass
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   root=toy)
    assert proc.returncode == 1
    assert "acceptance" in proc.stdout


def test_close_blocked_on_unreconciled_g3_touch(toy):
    """T2: the unit cannot close until touched-file declarations reconcile."""
    session = "close-g3"
    run_cli("slice", "--slice", "slice-042", "--session", session, root=toy)
    loaded_context(toy, session=session)
    (toy / "orders.py").write_text(GOOD_ORDERS)
    (toy / "rogue.py").write_text("x = 1\n")
    handle_event(make_event("post_change", session=session,
                            files=["orders.py", "rogue.py"]), toy)
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   root=toy)
    assert proc.returncode == 1
    out = json.loads(proc.stdout)
    assert "rogue.py" in json.dumps(out) and out.get("rule_ref") == "gate:G3"

    # reconciliation path: amend the declaration, then close succeeds
    from engine import read_jsonl, write_jsonl
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["predicted_files"].append("rogue.py")
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    handle_event(make_event("unit_complete", session=session), toy)
    proc2 = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                    root=toy)
    assert proc2.returncode == 0, proc2.stdout + proc2.stderr


def test_backlog_splits_oversized_slice(tmp_path):
    from conftest import build_toy_repo
    toy = build_toy_repo(tmp_path / "toy", budget=100)  # tiny budget
    proc = run_cli("backlog", root=toy)
    out = json.loads(proc.stdout)
    assert "slice-042" in out["split"]
    assert "slice-042-a" in out["slices"] and "slice-042-b" in out["slices"]
    from engine import read_jsonl
    rows = {r["id"]: r for r in read_jsonl(toy / ".harness" / "backlog.jsonl")}
    assert rows["slice-042-b"]["depends_on"] == ["slice-042-a"]
    deps_a = set(rows["slice-042-a"]["declares_dep"])
    deps_b = set(rows["slice-042-b"]["declares_dep"])
    assert deps_a | deps_b == {"telemetry", "config"} and not deps_a & deps_b


def test_init_scaffolds_and_refuses_overwrite(tmp_path):
    target = tmp_path / "fresh"
    target.mkdir()
    (target / "app.py").write_text("x = 1\n")
    proc = run_cli("init", root=target)
    assert proc.returncode == 0, proc.stderr
    assert "provenance" in proc.stdout.lower()
    for p in (".harness/config.yaml", ".harness/schema_version",
              ".harness/registry.jsonl", ".harness/decisions.jsonl",
              ".harness/backlog.jsonl", "adr/000-template.md",
              "contracts/api.yaml", ".github/workflows/harness-verify.yml"):
        assert (target / p).exists(), p
    cfg = (target / ".harness" / "config.yaml").read_text()
    assert "python: true" in cfg  # detected from app.py
    gi = (target / ".gitignore").read_text()
    assert ".harness/sidecar.db" in gi
    # refuses to overwrite
    proc2 = run_cli("init", root=target)
    assert proc2.returncode == 1
    assert "refusing" in proc2.stderr
