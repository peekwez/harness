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
