"""Regression tests for the parallel-worktree field report (W2–W6):
two concurrent builders in worktrees, disjoint predicted_files."""
import json
import subprocess
import sys

from conftest import (PLUGIN_ROOT, build_toy_repo, git, loaded_context,
                      make_event, run_cli)
from engine import read_jsonl, write_jsonl
from engine.events import Sidecar, handle_event

ADAPTER = PLUGIN_ROOT / "hooks" / "adapter.py"

GOOD_ORDERS = ("import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
               "    telemetry.emit_span('create_order', {'sku': sku})\n"
               "    return {'sku': sku}\n")


def run_adapter(hook: dict, cwd):
    return subprocess.run([sys.executable, str(ADAPTER)],
                          input=json.dumps(hook), capture_output=True,
                          text=True, cwd=str(cwd))


# ---------------------------------------------------------------- W2
def test_hook_adapter_routes_edit_to_the_files_substrate_root(toy, tmp_path):
    """A builder edits inside a worktree while the hook process runs in the
    main tree: the event must land in the WORKTREE's substrate, not vanish
    as an out-of-root path in the main tree's."""
    wt = build_toy_repo(tmp_path / "wt-slice-008")
    (wt / "orders.py").write_text(GOOD_ORDERS)
    hook = {"hook_event_name": "PostToolUse", "session_id": "wt-sess",
            "cwd": str(toy),
            "tool_input": {"file_path": str(wt / "orders.py")}}
    proc = run_adapter(hook, cwd=toy)   # hook process cwd = main tree
    assert proc.returncode == 0, proc.stdout + proc.stderr
    sc = Sidecar(wt)
    try:
        assert "orders.py" in sc.touched_paths(session_id="wt-sess")
    finally:
        sc.close()
    sc_main = Sidecar(toy)
    try:
        assert "orders.py" not in sc_main.touched_paths(session_id="wt-sess")
    finally:
        sc_main.close()


def test_hook_adapter_stop_regenerates_shadows_in_the_worktree(toy, tmp_path):
    """Stop (unit_complete) carries no file paths — the hook's cwd must
    route it, so touched-file shadows regenerate inside the worktree."""
    wt = build_toy_repo(tmp_path / "wt-slice-009")
    (wt / "orders.py").write_text(GOOD_ORDERS)
    loaded_context(wt, session="wt-sess")
    run_adapter({"hook_event_name": "PostToolUse", "session_id": "wt-sess",
                 "cwd": str(wt),
                 "tool_input": {"file_path": str(wt / "orders.py")}}, cwd=toy)
    proc = run_adapter({"hook_event_name": "Stop", "session_id": "wt-sess",
                        "cwd": str(wt)}, cwd=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (wt / ".harness" / "shadows" / "orders.py.json").exists()


# ---------------------------------------------------------------- W3
def test_close_extracts_missing_shadows_instead_of_passing_silently(toy):
    """G7 asymmetry (W3): a brand-new predicted file with NO shadow sailed
    through close — the md-file-bug class. The ruled contract: close
    extracts the missing shadows itself (derived artifacts are the engine's
    job) and reports them; it must never silently pass without them."""
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["predicted_files"] = ["orders.py", "newcli.py"]
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    session = "wt-close"
    run_cli("slice", "--slice", "slice-042", "--session", session, root=toy)
    loaded_context(toy, session=session)
    (toy / "orders.py").write_text(GOOD_ORDERS)
    (toy / "newcli.py").write_text("def main() -> int:\n    return 0\n")
    handle_event(make_event("post_change", session=session,
                            files=["orders.py", "newcli.py"]), toy)
    # NO unit_complete for this session: shadows were never regenerated
    # (the worktree hook gap) — close runs under an explicitly DIFFERENT
    # session (Y2 would otherwise join the live one), so the ceremony's
    # session-scoped regeneration can't cover them either.
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "slice-042: orders + cli")
    head = git(toy, "rev-parse", "HEAD").stdout.strip()
    proc = run_cli("close-slice", "--slice", "slice-042", "--commit", head,
                   "--session", "someone-else", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["closed"]
    assert set(out["shadows_extracted"]) >= {"orders.py", "newcli.py"}
    assert (toy / ".harness" / "shadows" / "newcli.py.json").exists()


# ---------------------------------------------------------------- W4
def test_close_commits_its_own_substrate_mutations(toy):
    """The backlog status flip + telemetry land AFTER the commit the
    ceremony stamps — close must commit its substrate mutations itself or
    the flip is lost on worktree merge."""
    session = "close-commit"
    run_cli("slice", "--slice", "slice-042", "--session", session, root=toy)
    loaded_context(toy, session=session)
    (toy / "orders.py").write_text(GOOD_ORDERS)
    handle_event(make_event("post_change", session=session,
                            files=["orders.py"]), toy)
    handle_event(make_event("unit_complete", session=session), toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "slice-042: orders service")
    head = git(toy, "rev-parse", "HEAD").stdout.strip()

    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", head, root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["closed"]
    assert out.get("substrate_commit"), \
        "close must report the follow-up substrate commit"
    # nothing under .harness left uncommitted
    dirty = git(toy, "status", "--porcelain", "--", ".harness").stdout.strip()
    assert not dirty, f"substrate left dirty after close: {dirty}"
    committed = git(toy, "show", "HEAD:.harness/backlog.jsonl").stdout
    assert '"closed"' in committed, "status flip must be IN a commit"
    # the feature commit the note points at is untouched (no amend —
    # amending would orphan the git note)
    assert git(toy, "rev-parse", f"{head}^{{commit}}").returncode == 0
    assert out["note_written"]


# ---------------------------------------------------------------- W5
def test_merge_substrate_keyed_3way(tmp_path):
    base = tmp_path / "base.jsonl"
    ours = tmp_path / "ours.jsonl"
    theirs = tmp_path / "theirs.jsonl"
    write_jsonl(base, [{"id": "slice-008", "status": "in_progress"},
                       {"id": "slice-009", "status": "in_progress"}])
    write_jsonl(ours, [{"id": "slice-008", "status": "closed"},
                       {"id": "slice-009", "status": "in_progress"},
                       {"id": "slice-010", "status": "planned"}])
    write_jsonl(theirs, [{"id": "slice-008", "status": "in_progress"},
                         {"id": "slice-009", "status": "closed"},
                         {"id": "slice-011", "status": "planned"}])
    proc = run_cli("merge-substrate", base, ours, theirs)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    merged = {r["id"]: r for r in read_jsonl(ours)}
    assert merged["slice-008"]["status"] == "closed"      # ours' change kept
    assert merged["slice-009"]["status"] == "closed"      # theirs' change taken
    assert set(merged) == {"slice-008", "slice-009", "slice-010", "slice-011"}


def test_merge_substrate_conflicting_row_fails_loud(tmp_path):
    base = tmp_path / "base.jsonl"
    ours = tmp_path / "ours.jsonl"
    theirs = tmp_path / "theirs.jsonl"
    write_jsonl(base, [{"id": "s", "status": "planned"}])
    write_jsonl(ours, [{"id": "s", "status": "closed"}])
    write_jsonl(theirs, [{"id": "s", "status": "in_progress"}])
    before = ours.read_text()
    proc = run_cli("merge-substrate", base, ours, theirs)
    assert proc.returncode == 1
    assert "s" in (proc.stdout + proc.stderr)
    assert ours.read_text() == before  # left for manual resolution


def test_init_installs_substrate_merge_drivers(tmp_path):
    root = tmp_path / "fresh"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n")
    git(root, "init", "-q")
    proc = run_cli("init", root=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    ga = (root / ".gitattributes").read_text()
    assert ".harness/telemetry.jsonl merge=union" in ga
    assert ".harness/edges.jsonl merge=union" in ga
    assert ".harness/backlog.jsonl merge=harness-substrate" in ga
    assert ".harness/registry.jsonl merge=harness-substrate" in ga
    driver = git(root, "config", "merge.harness-substrate.driver").stdout
    assert "merge-substrate %O %A %B" in driver


def test_parallel_close_branches_merge_without_conflict(tmp_path):
    """The W5 scenario end-to-end: two branches each flip their own backlog
    row and append telemetry; the second merge must not conflict."""
    root = tmp_path / "para"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n")
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@t")
    git(root, "config", "user.name", "t")
    proc = run_cli("init", root=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    backlog = root / ".harness" / "backlog.jsonl"
    write_jsonl(backlog, [{"id": "slice-a", "status": "in_progress"},
                          {"id": "slice-b", "status": "in_progress"}])
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    default = git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    for branch, other in (("slice-a", "slice-b"), ("slice-b", "slice-a")):
        git(root, "checkout", "-q", default)
        git(root, "checkout", "-qb", branch)
        write_jsonl(backlog, [{"id": branch, "status": "closed"},
                              {"id": other, "status": "in_progress"}])
        with (root / ".harness" / "telemetry.jsonl").open("a") as fh:
            fh.write(json.dumps({"ev": branch}) + "\n")
        git(root, "commit", "-qam", branch)

    git(root, "checkout", "-q", default)
    assert git(root, "merge", "-q", "--no-edit", "slice-a").returncode == 0
    second = git(root, "merge", "--no-edit", "slice-b")
    assert second.returncode == 0, second.stdout + second.stderr
    merged = {r["id"]: r["status"] for r in read_jsonl(backlog)}
    assert merged == {"slice-a": "closed", "slice-b": "closed"}
    tel = (root / ".harness" / "telemetry.jsonl").read_text()
    assert '"slice-a"' in tel and '"slice-b"' in tel  # union kept both


# ---------------------------------------------------------------- W6b
def test_python_class_fields_surface_in_shadow(toy):
    """slice-009 had to confirm `max_count` from ADR prose because the
    config shadow exposed Settings but not its fields."""
    from engine import load_config
    from engine.extractor.engine import extract_path
    (toy / "settings.py").write_text(
        "class Settings:\n"
        '    """App settings."""\n'
        "    max_count: int = 100\n"
        "    name = \"harness\"\n"
        "    _internal = True\n\n"
        "    def reload(self) -> None:\n"
        "        pass\n\n\n"
        "def get_settings() -> Settings:\n"
        "    return Settings()\n")
    shadow, _ = extract_path(toy, toy / "settings.py", load_config(toy))
    fields = {s["name"]: s for s in shadow["symbols"] if s["kind"] == "field"}
    assert "Settings.max_count" in fields
    assert "max_count: int = 100" in fields["Settings.max_count"]["signature"]
    assert fields["Settings.name"]["visibility"] == "public"
    assert fields["Settings._internal"]["visibility"] == "private"
    # fields are interface detail, not module exports
    assert "Settings.max_count" not in shadow["exports"]
    assert "Settings" in shadow["exports"]
