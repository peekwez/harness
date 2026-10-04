"""engine.upgrade_report: what changed, what the human checks, one commit."""
from __future__ import annotations

import shutil
import subprocess

from conftest import ASTRA_ORDERS_PY, _write, build_astralabs_094_repo, git
from engine import upgrade_report as rep


def test_snapshot_covers_tracked_and_untracked_but_not_ignored_or_machine_state(tmp_path):
    root = build_astralabs_094_repo(tmp_path / "astra")
    _write(root, "notes.txt", "draft\n")
    _write(root, ".harness/cache/shadows/x.json", "{}")
    snap = rep.snapshot(root)
    assert "notes.txt" in snap and ".harness/registry.jsonl" in snap
    assert snap["assets/demo.mp4"].startswith("sha256:")
    assert not any(p.startswith(("site/", ".harness/cache/")) for p in snap)


def test_snapshot_outside_git_walks_the_tree(tmp_path):
    root = tmp_path / "plain"
    _write(root, ".harness/config.yaml", "schema: 2\n")
    _write(root, ".harness/sidecar.db", b"\x00")
    _write(root, "node_modules/x.js", "x")
    assert set(rep.snapshot(root)) == {".harness/config.yaml"}


def test_changed_files_names_added_modified_and_removed():
    before = {"a": "h1", "b": "h2", "c": "h3", "d": None}
    after = {"a": "h1", "b": "h9", "d": "h4", "e": "h5"}
    assert rep.changed_files(before, after) == {
        "added": ["d", "e"], "modified": ["b"], "removed": ["c"]}


def test_commit_proposal_adds_only_upgrade_paths_and_runs_verbatim(tmp_path):
    root = build_astralabs_094_repo(tmp_path / "my repo's copy")
    orders = "libs/core/src/astra_core/orders.py"
    _write(root, orders, ASTRA_ORDERS_PY + "# work in progress\n")   # the human's edit
    before = rep.snapshot(root)
    git(root, "rm", "-rq", "--cached", ".harness/shadows")            # what W1 does
    shutil.rmtree(root / ".harness/shadows")
    _write(root, ".claude/memory/shared/MEMORY.md", "# Shared memory\n")
    _write(root, "docs/upgrade notes.md", "notes\n")
    _write(root, ".harness/schema_version", "2\n")
    files = rep.changed_files(before, rep.snapshot(root))
    proposal = rep.commit_proposal(root, files)
    assert proposal["message"] == "harness: upgrade to 0.10"
    assert orders not in proposal["paths"]
    assert "'docs/upgrade notes.md'" in proposal["command"]
    assert proposal["command"].endswith('git commit -m "harness: upgrade to 0.10"')
    done = subprocess.run(["bash", "-c", proposal["command"]], cwd=proposal["cwd"],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert git(root, "log", "-1", "--format=%s").stdout.strip() == "harness: upgrade to 0.10"
    assert git(root, "status", "--porcelain").stdout.strip() == f"M {orders}"
    assert git(root, "ls-files", ".harness/shadows").stdout == ""


def test_no_commit_proposal_outside_git_or_without_changes(tmp_path):
    (tmp_path / "plain").mkdir()
    assert rep.commit_proposal(tmp_path / "plain",
                               {"added": ["a"], "modified": [], "removed": []}) is None
    root = build_astralabs_094_repo(tmp_path / "astra")
    assert rep.commit_proposal(root, {"added": [], "modified": [], "removed": []}) is None


def test_staged_and_dirty_paths(tmp_path):
    root = build_astralabs_094_repo(tmp_path / "astra")
    _write(root, "docs/index.md", "# Astra\n\nChanged.\n")
    _write(root, "notes.txt", "x\n")
    git(root, "add", "notes.txt")
    assert rep.staged_paths(root) == ["notes.txt"]
    assert rep.dirty_paths(root) == ["docs/index.md", "notes.txt"]


def test_human_checks_collect_step_checks_skips_and_staged_work():
    steps = [{"id": "w1.x", "title": "t",
              "report": ["removed .harness/shadows/", "check: AGENTS.md has no marker. Add: line"]},
             {"id": "w3.y", "title": "t", "report": ["skipped: needs confirmation"]}]
    out = rep.human_checks(
        steps, pending=["w3.y"], staged_before=["notes.txt"], dirty_before=["AGENTS.md"],
        files={"added": [], "modified": ["AGENTS.md"], "removed": []},
        checks={"doctor": {"deps_missing": ["tree-sitter"]}}, is_repo=True)
    joined = "\n".join(out)
    assert "w1.x: check: AGENTS.md has no marker. Add: line" in joined
    assert "w3.y: skipped: needs confirmation" in joined
    assert "harness upgrade --yes" in joined
    assert "notes.txt" in joined and "AGENTS.md" in joined
    assert "pip install tree-sitter" in joined
    assert "removed .harness/shadows/" not in joined


def test_human_checks_include_step_advice_rows():
    out = rep.human_checks(
        [], pending=[], staged_before=[], dirty_before=[],
        files={"added": [], "modified": [], "removed": []}, checks={},
        is_repo=True,
        advice=[{"id": "w3.claude-md-import",
                 "check": "check: CLAUDE.md has no harness marker."}])
    assert out == ["w3.claude-md-import: check: CLAUDE.md has no harness marker."]


def test_step_lines_fall_back_to_changes():
    assert rep.step_lines({"id": "w1.x", "changes": ["a"]}) == ["a"]
    assert rep.step_lines({"id": "w1.x", "report": ["b"], "changes": ["a"]}) == ["b"]


def test_literal_pathspecs_keep_the_humans_dirty_neighbour_out(tmp_path):
    root = build_astralabs_094_repo(tmp_path / "astra")
    _write(root, "a1.txt", "one\n")
    _write(root, "a[1].txt", "old\n")
    git(root, "add", "a1.txt", "a[1].txt")
    git(root, "commit", "-qm", "base")
    before = rep.snapshot(root)
    _write(root, "a[1].txt", "upgraded\n")
    files = rep.changed_files(before, rep.snapshot(root))
    _write(root, "a1.txt", "human edit\n")
    proposal = rep.commit_proposal(root, files)
    done = subprocess.run(["bash", "-c", proposal["command"]], cwd=proposal["cwd"],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert git(root, "status", "--porcelain").stdout.strip() == "M a1.txt"


def test_staged_before_raises_the_commit_or_unstage_check():
    out = rep.human_checks(
        [], pending=[], staged_before=["notes.txt"], dirty_before=[],
        files={"added": [], "modified": [], "removed": []}, checks={}, is_repo=True)
    assert len(out) == 1 and "Commit or unstage them first" in out[0]


def test_long_file_lists_are_capped_and_the_fix_stays_last():
    names = [f"f{i}.txt" for i in range(40)]
    out = rep.human_checks(
        [], pending=[], staged_before=names, dirty_before=[],
        files={"added": [], "modified": [], "removed": []}, checks={}, is_repo=True)
    assert "and 37 more" in out[0] and "f5.txt" not in out[0]
    assert len(out[0].split()) <= 25 and out[0].endswith("unstage them first.")


def test_staged_rename_shows_the_old_path(tmp_path):
    root = build_astralabs_094_repo(tmp_path / "astra")
    git(root, "mv", "docs/index.md", "docs/home.md")
    assert rep.staged_paths(root) == ["docs/home.md", "docs/index.md"]


def test_a_failing_git_call_raises_instead_of_reading_empty(tmp_path):
    import pytest
    from engine import HarnessError
    (tmp_path / ".git").mkdir()
    with pytest.raises(HarnessError, match="git diff failed"):
        rep.staged_paths(tmp_path)


def test_verify_blocks_become_failures_with_their_fix():
    report = {"passed": False, "findings": [
        {"code": "SCHEMA_INVALID", "severity": "block",
         "message": "registry.jsonl: row 'x' is missing required field 'kind'",
         "fix": "add the field"},
        {"code": "LEGACY_GRAPH_PROVENANCE", "severity": "advisory", "message": "old"}]}
    assert rep.verify_failures(report) == [{
        "check": "verify", "code": "SCHEMA_INVALID",
        "text": "registry.jsonl: row 'x' is missing required field 'kind'",
        "fix": "add the field"}]


def test_verify_failure_without_fix_points_at_gates_explain():
    out = rep.verify_failures({"passed": False, "findings": [
        {"code": "EXPLORE_IMPORT", "severity": "block", "message": "m"}]})
    assert out[0]["fix"] == "harness gates explain EXPLORE_IMPORT"


def test_doctor_failures_name_each_problem_and_its_fix():
    report = {"substrate_healthy": False,
              "schema_problems": ["backlog.jsonl:2: bad status"],
              "stale_worktrees": [{"path": "/r/.worktrees/ghost", "slice": "ghost",
                                   "reason": "no such slice",
                                   "remove_with": "git worktree remove --force /r/.worktrees/ghost"}],
              "parked_findings": 2, "stale_bindings": [],
              "vendored_engine": {"status": "current"}, "next": "harness adjudicate --list"}
    out = rep.doctor_failures(report)
    assert [f["code"] for f in out] == ["schema_problems", "stale_worktrees", "parked_findings"]
    assert out[1]["fix"] == "git worktree remove --force /r/.worktrees/ghost"
    assert out[2]["fix"] == "harness adjudicate --list"


def test_unhealthy_doctor_with_an_unknown_reason_still_fails():
    out = rep.doctor_failures({"substrate_healthy": False, "next": "harness doctor --substrate --fix"})
    assert out == [{"check": "doctor", "code": "unhealthy",
                    "text": "doctor reports the substrate unhealthy",
                    "fix": "harness doctor --substrate --fix"}]


def test_healthy_doctor_has_no_failures():
    assert rep.doctor_failures({"substrate_healthy": True,
                                "stale_worktrees": [{"x": 1}]}) == []


def test_a_crashed_check_is_a_failure():
    assert rep.verify_failures({"error": "Traceback"})[0]["code"] == "VERIFY_CRASHED"
    assert rep.doctor_failures({"error": "Traceback"})[0]["code"] == "DOCTOR_CRASHED"


def test_attribute_names_the_last_step_that_reported_the_file():
    steps = [{"id": "w1.drop-registry-shadow", "report": ["rewrote .harness/registry.jsonl (3 rows)"]},
             {"id": "w2.telemetry", "report": ["wrote .harness/slice-metrics.jsonl"]}]
    failures = [
        {"check": "verify", "code": "SCHEMA_INVALID", "text": "registry.jsonl: row 'x' bad", "fix": "f"},
        {"check": "doctor", "code": "stale_worktrees", "text": '{"slice": "ghost"}', "fix": "g"},
        {"check": "upgrade", "code": "STEP_FAILED", "text": "boom", "fix": "h", "step": "w3.z"}]
    out = rep.attribute(failures, steps)
    assert [f["step"] for f in out] == ["w1.drop-registry-shadow", "none", "w3.z"]
    assert out[0]["line"] == ("verify SCHEMA_INVALID: registry.jsonl: row 'x' bad. "
                              "Step: w1.drop-registry-shadow. Fix: f")


def test_reported_step_errors():
    rows = [{"id": "w2.a", "report": []}, {"id": "w2.b", "error": "disk full"}]
    assert rep.reported_step_errors(rows) == [{
        "check": "upgrade", "code": "STEP_FAILED", "text": "disk full", "step": "w2.b",
        "fix": "fix the cause, then run: harness upgrade --yes"}]


def test_status_rules():
    none = {"added": [], "modified": [], "removed": []}
    some = {"added": ["a"], "modified": [], "removed": []}
    skip = [{"id": "w1.x", "report": ["skipped: needs confirmation"]}]
    kw = dict(current=2, steps=[], pending=[], failures=[])
    assert rep.upgrade_status(schema_from=2, files=none, **kw) == "already on 0.10"
    assert rep.upgrade_status(schema_from=1, files=some, **kw) == "upgraded"
    assert rep.upgrade_status(schema_from=1, files=none, **kw) == "upgraded"
    assert rep.upgrade_status(schema_from=1, current=2, files=some, steps=skip,
                              pending=["w1.x"], failures=[]) == "incomplete"
    assert rep.upgrade_status(schema_from=1, current=2, files=some, steps=skip,
                              pending=[], failures=[]) == "incomplete"
    assert rep.upgrade_status(schema_from=1, current=2, files=some, steps=[], pending=[],
                              failures=[{"code": "SCHEMA_INVALID"}]) == "checks failed"
    assert rep.upgrade_status(schema_from=1, current=2, files=some, steps=[], pending=[],
                              failures=[{"code": "STEP_FAILED"}]) == "failed"


def test_final_checks_run_doctor_and_verify_in_fresh_processes(tmp_path):
    root = build_astralabs_094_repo(tmp_path / "astra")
    out = rep.final_checks(root)
    assert set(out) == {"doctor", "verify"}
    assert isinstance(out["doctor"]["failures"], list) and isinstance(out["verify"]["passed"], bool)
    assert rep.HARNESS_BIN.name == "harness"


def test_a_stage_that_raises_becomes_a_short_failure_row():
    failures = []
    assert rep.run_stage(failures, "refresh workflow", lambda: 1 / 0, {}) == {}
    assert rep.run_stage(failures, "list files", lambda: 7) == 7
    [row] = rep.attribute(failures, [])
    assert row["code"] == "STAGE_FAILED" and row["stage"] == "refresh workflow"
    assert row["detail"] == "division by zero"
    assert row["line"] == ("upgrade STAGE_FAILED: stage refresh workflow raised "
                           "ZeroDivisionError. Step: none. Fix: " + rep.STEP_FIX)
    assert len(row["line"].split()) <= 25 and row["line"].endswith("--yes")
    assert "owner" not in row


def test_a_raising_describe_counts_as_pending():
    class S:
        def __init__(self, id, describe):
            self.id, self.describe = id, describe

    def boom(root):
        raise ValueError("bad yaml")
    steps = [S("a", lambda r: []), S("b", boom), S("c", lambda r: ["x"])]
    assert rep.pending_ids(".", steps) == ["b", "c"]


def test_a_stage_failure_fails_the_upgrade():
    assert rep.upgrade_status(schema_from=1, current=2, files={"added": ["a"], "modified": [],
                              "removed": []}, steps=[], pending=[],
                              failures=[{"code": "STAGE_FAILED"}]) == "failed"
