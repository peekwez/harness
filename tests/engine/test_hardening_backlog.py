"""Regression coverage for backlog and binding hardening."""
from __future__ import annotations

import json

from conftest import build_toy_repo, git, run_cli
from engine import read_jsonl, write_jsonl
from engine.graph import load_edges


def _add_open_dependency(toy):
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["depends_on"] = ["slice-000"]
    rows.append({
        "id": "slice-000", "spec": "spec-007", "title": "foundation",
        "status": "planned", "declares_dep": [], "acceptance": [],
        "predicted_files": [], "context_cost_estimate": 0,
        "depends_on": [], "worktree": None,
    })
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    git(toy, "add", "-A")
    assert git(toy, "commit", "-qm", "add open dependency").returncode == 0


def _override_edges(root):
    return [e for e in load_edges(root)
            if e["type"] == "override"
            and e.get("meta", {}).get("kind") == "dependency_order"]


def test_split_child_id_collision_is_refused_before_any_write(tmp_path):
    toy = build_toy_repo(tmp_path / "split", oversized=True)
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows.append({
        "id": "slice-042-a", "spec": "other", "title": "existing child id",
        "status": "planned", "declares_dep": [],
        "acceptance": ["tests/slices/042_orders.py"],
        "predicted_files": ["existing.py"], "context_cost_estimate": 0,
        "depends_on": [], "worktree": None,
    })
    backlog = toy / ".harness" / "backlog.jsonl"
    write_jsonl(backlog, rows)
    before = backlog.read_bytes()

    proc = run_cli("backlog", "--split", root=toy)

    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert backlog.read_bytes() == before
    out = json.loads(proc.stdout)
    assert out["split"] == []
    assert "slice-042-a" in out["reason"]
    assert "already exist" in out["reason"]


def test_split_reports_proposal_without_cloning_parent_contract(tmp_path):
    toy = build_toy_repo(tmp_path / "proposal", oversized=True)
    backlog = toy / ".harness" / "backlog.jsonl"
    parent_before = read_jsonl(backlog)[0]

    proc = run_cli("backlog", "--split", root=toy)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["split"] == []
    proposal = out["split_proposals"][0]
    assert proposal["id"] == "slice-042"
    assert proposal["child_ids"] == ["slice-042-a", "slice-042-b"]
    assert "authored" in proposal["reason"]
    assert "acceptance" in proposal["reason"]
    assert "predicted_files" in proposal["reason"]
    rows = read_jsonl(backlog)
    assert [row["id"] for row in rows] == ["slice-042"]
    parent_after = rows[0]
    assert parent_after["acceptance"] == parent_before["acceptance"]
    assert parent_after["predicted_files"] == parent_before["predicted_files"]
    assert parent_after["declares_dep"] == parent_before["declares_dep"]
    assert parent_after["depends_on"] == parent_before["depends_on"]


def test_direct_slice_binding_cannot_bypass_open_dependency(tmp_path):
    toy = build_toy_repo(tmp_path / "bind")
    _add_open_dependency(toy)

    proc = run_cli("slice", "--slice", "slice-042", "--session", "bypass",
                   root=toy)

    assert proc.returncode == 1, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["bound"] is False
    assert out["rule_ref"] == "gate:G1"
    assert "slice-000" in out["reason"]
    row = next(r for r in read_jsonl(toy / ".harness" / "backlog.jsonl")
               if r["id"] == "slice-042")
    assert row["status"] == "planned"
    assert _override_edges(toy) == []


def test_force_requires_a_nonwhitespace_reason_before_creating_worktree(tmp_path):
    toy = build_toy_repo(tmp_path / "blank-force")
    _add_open_dependency(toy)

    proc = run_cli("start", "--slice", "slice-042", "--force",
                   "--justification", "   \t", root=toy)

    assert proc.returncode == 2
    assert "justification" in proc.stderr
    assert not (toy / ".worktrees" / "slice-042").exists()
    assert _override_edges(toy) == []


def test_start_rejects_path_like_slice_id_before_creating_worktree(tmp_path):
    toy = build_toy_repo(tmp_path / "unsafe-id")
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["id"] = "nested/slice-042"
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)

    proc = run_cli("start", "--slice", "nested/slice-042", root=toy)

    assert proc.returncode == 2
    assert "slice id" in proc.stderr.lower()
    assert not (toy / ".worktrees").exists()


def test_forced_start_records_override_only_in_target_and_once_on_resume(tmp_path):
    toy = build_toy_repo(tmp_path / "force")
    _add_open_dependency(toy)

    first = run_cli("start", "--slice", "slice-042", "--force",
                    "--justification", "same release", root=toy)
    assert first.returncode == 0, first.stdout + first.stderr
    wt = toy / ".worktrees" / "slice-042"
    assert _override_edges(toy) == []
    assert len(_override_edges(wt)) == 1
    assert not git(toy, "status", "--short", "--",
                   ".harness/edges.jsonl").stdout.strip()

    second = run_cli("start", "--slice", "slice-042", "--force",
                     "--justification", "same release", root=toy)
    assert second.returncode == 0, second.stdout + second.stderr
    assert json.loads(second.stdout)["resumed"] is True
    assert len(_override_edges(wt)) == 1


def test_closed_slice_cannot_be_bound_for_more_writes(toy):
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["status"] = "closed"
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)

    proc = run_cli("slice", "--slice", "slice-042", "--session", "late",
                   root=toy)

    assert proc.returncode == 1, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["bound"] is False
    assert "closed" in out["reason"]
