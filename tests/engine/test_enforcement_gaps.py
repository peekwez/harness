"""Declarations the system recorded but never enforced: slice dependency
order, substrate row schemas, and repo health."""
import json

from conftest import git, run_cli
from engine import read_jsonl, write_jsonl


def _add_dep_slice(toy, dep_status="planned"):
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["depends_on"] = ["slice-000"]
    rows.append({"id": "slice-000", "spec": "spec-007", "title": "foundation",
                 "status": dep_status, "declares_dep": [], "acceptance": [],
                 "predicted_files": [], "context_cost_estimate": 0,
                 "depends_on": [], "worktree": None})
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)


# ---------------------------------------------------------------- dependencies
def test_start_refuses_a_slice_whose_dependency_is_open(toy):
    """depends_on was recorded, cost-estimated and displayed — but nothing
    stopped starting out of order. Every other declaration is enforced."""
    _add_dep_slice(toy)
    proc = run_cli("start", "--slice", "slice-042", "--no-worktree", root=toy)
    assert proc.returncode == 1, proc.stdout
    out = json.loads(proc.stdout)
    assert "slice-000" in out["reason"]
    assert out["rule_ref"] == "gate:G1"
    # nothing was bound
    rows = {r["id"]: r for r in read_jsonl(toy / ".harness" / "backlog.jsonl")}
    assert rows["slice-042"]["status"] == "planned"


def test_start_allows_once_the_dependency_is_closed(toy):
    _add_dep_slice(toy, dep_status="closed")
    proc = run_cli("start", "--slice", "slice-042", "--no-worktree", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_start_force_records_an_auditable_override(toy):
    _add_dep_slice(toy)
    proc = run_cli("start", "--slice", "slice-042", "--no-worktree", "--force",
                   "--justification", "foundation lands in the same PR",
                   root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    from engine.graph import load_edges
    edge = next(e for e in load_edges(toy)
                if e["type"] == "override" and e["to"] == "slice:slice-000")
    assert edge["meta"]["justification"].startswith("foundation")
    assert edge["meta"]["rule_ref"] == "gate:G1"


def test_force_without_justification_is_refused(toy):
    _add_dep_slice(toy)
    proc = run_cli("start", "--slice", "slice-042", "--no-worktree", "--force",
                   root=toy)
    assert proc.returncode == 2
    assert "justification" in proc.stderr


def test_unknown_dependency_is_named(toy):
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["depends_on"] = ["slice-ghost"]
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    proc = run_cli("start", "--slice", "slice-042", "--no-worktree", root=toy)
    assert proc.returncode == 1
    assert "slice-ghost" in json.loads(proc.stdout)["reason"]


# ---------------------------------------------------------------- schemas
def test_verify_validates_backlog_rows(toy):
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0].pop("acceptance")                    # required by §5.6
    rows[0]["predicted_files"] = "orders.py"     # must be a list
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    proc = run_cli("verify", root=toy)
    assert proc.returncode == 1
    msgs = [f["message"] for f in json.loads(proc.stdout)["findings"]
            if f["code"] == "SCHEMA_INVALID"]
    assert any("acceptance" in m and "slice-042" in m for m in msgs), msgs
    assert any("predicted_files" in m for m in msgs), msgs


def test_verify_validates_registry_and_decision_rows(toy):
    reg = read_jsonl(toy / ".harness" / "registry.jsonl")
    reg[0]["status"] = "halfway"                 # not a legal status
    write_jsonl(toy / ".harness" / "registry.jsonl", reg)
    dec = read_jsonl(toy / ".harness" / "decisions.jsonl")
    dec[0].pop("answer")                         # required by §5.5
    write_jsonl(toy / ".harness" / "decisions.jsonl", dec)
    proc = run_cli("verify", root=toy)
    assert proc.returncode == 1
    msgs = [f["message"] for f in json.loads(proc.stdout)["findings"]
            if f["code"] == "SCHEMA_INVALID"]
    assert any("halfway" in m for m in msgs), msgs
    assert any("answer" in m and "D-041" in m for m in msgs), msgs


def test_valid_substrate_produces_no_schema_findings(toy):
    proc = run_cli("verify", root=toy)
    assert "SCHEMA_INVALID" not in proc.stdout


# ---------------------------------------------------------------- doctor
def test_doctor_substrate_reports_repo_health(toy):
    from engine.events import Sidecar
    # 1. a binding pointing at a closed slice
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["status"] = "closed"
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    sc = Sidecar(toy)
    try:
        sc.state_set("ghost-session", "active_slice", "slice-042")
    finally:
        sc.close()
    # 2. an unadjudicated park
    run_cli("review", "--slice", "slice-042", "--park", "--code",
            "REVIEW_UNCERTAIN", "--rule-ref", "gate:G5", "--message", "q",
            root=toy)
    # 3. a worktree with no matching branch
    (toy / ".worktrees" / "slice-abandoned").mkdir(parents=True)

    proc = run_cli("doctor", "--substrate", root=toy)
    assert proc.returncode == 1, proc.stdout
    out = json.loads(proc.stdout)
    assert out["healthy"] is False
    assert "slice-042" in json.dumps(out["stale_bindings"])
    assert out["parked_findings"] == 1
    assert "slice-abandoned" in json.dumps(out["stale_worktrees"])
    assert out["missing_notes"], "a closed slice with no note is unhealthy"


def test_doctor_fix_clears_what_is_safe_to_clear(toy):
    from engine.events import Sidecar
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["status"] = "closed"
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    sc = Sidecar(toy)
    try:
        sc.state_set("ghost-session", "active_slice", "slice-042")
    finally:
        sc.close()
    proc = run_cli("doctor", "--substrate", "--fix", root=toy)
    out = json.loads(proc.stdout)
    assert out["fixed"]["bindings_released"] >= 1
    sc = Sidecar(toy)
    try:
        assert sc.state_get("ghost-session", "active_slice") is None
    finally:
        sc.close()
    # destructive things are reported, never auto-removed
    assert "stale_worktrees" in out


def test_doctor_healthy_substrate_exits_zero(toy):
    proc = run_cli("doctor", "--substrate", root=toy)
    assert proc.returncode == 0, proc.stdout
    assert json.loads(proc.stdout)["healthy"] is True
