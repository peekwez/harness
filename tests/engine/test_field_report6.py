"""Regression tests for field report round 5 (Y1–Y3) and the last two
orchestrator-manual ceremonies (imp-3 `backlog add`, imp-4 `merge-slice`)."""
import json

from conftest import git, loaded_context, make_event, run_cli
from engine import read_jsonl
from engine.events import Sidecar, handle_event

GOOD_ORDERS = ("import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
               "    telemetry.emit_span('create_order', {'sku': sku})\n"
               "    return {'sku': sku}\n")

NO_ENV = {"CLAUDE_SESSION_ID": ""}   # neutralize any ambient session export


# ---------------------------------------------------------------- Y1
def test_close_rejects_a_commit_missing_the_touched_files(toy):
    """`git add -N` produced a commit WITHOUT the slice's sources and the
    provenance note landed on the wrong commit — close must check the
    named commit's tree actually contains the touched files."""
    session = "y1"
    run_cli("slice", "--slice", "slice-042", "--session", session, root=toy)
    loaded_context(toy, session=session)
    (toy / "orders.py").write_text(GOOD_ORDERS)
    handle_event(make_event("post_change", session=session,
                            files=["orders.py"]), toy)
    handle_event(make_event("unit_complete", session=session), toy)
    git(toy, "add", "-N", "orders.py")            # intent-to-add: no content
    git(toy, "commit", "-qm", "empty-ish", "--allow-empty",
        "--", ":(exclude)orders.py")
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 1, proc.stdout
    out = json.loads(proc.stdout)
    assert "orders.py" in out["reason"]
    assert "commit" in out["reason"]
    # after a REAL commit, the same close succeeds
    git(toy, "add", "orders.py")
    git(toy, "commit", "-qm", "orders for real")
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# ---------------------------------------------------------------- Y2
def test_cli_joins_the_live_hook_session_when_env_is_absent(toy):
    """Builder shells often lack $CLAUDE_SESSION_ID; the hook events carry
    the real UUID — the CLI must join that session, not fall back to a
    'cli' session the gates never saw."""
    loaded_context(toy, session="hook-uuid-77")   # hook records the live id
    proc = run_cli("slice", "--slice", "slice-042", root=toy, env=NO_ENV)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["session"] == "hook-uuid-77"
    sc = Sidecar(toy)
    try:
        assert sc.state_get("hook-uuid-77", "active_slice") == "slice-042"
    finally:
        sc.close()


def test_cli_sessions_never_become_the_live_hook_session(toy):
    """CLI-originated events (session 'cli') must not clobber the recorded
    live hook session."""
    loaded_context(toy, session="hook-uuid-88")
    handle_event(make_event("post_change", session="cli",
                            files=["orders.py"]), toy)
    proc = run_cli("slice", "--slice", "slice-042", root=toy, env=NO_ENV)
    assert json.loads(proc.stdout)["session"] == "hook-uuid-88"


# ---------------------------------------------------------------- imp-3
def test_backlog_add_appends_a_valid_row(toy):
    proc = run_cli("backlog", "add", "--id", "slice-050",
                   "--title", "cli-added slice", "--spec", "spec-007",
                   "--declares", "telemetry",
                   "--predicts", "src/newthing.py",
                   "--acceptance", "tests/slices/050_newthing.py",
                   "--depends", "slice-042", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rows = {r["id"]: r for r in read_jsonl(toy / ".harness" / "backlog.jsonl")}
    row = rows["slice-050"]
    assert row["status"] == "planned"
    assert row["declares_dep"] == ["telemetry"]
    assert "tests/slices/050_newthing.py" in row["predicted_files"]
    assert row["depends_on"] == ["slice-042"]
    assert isinstance(row["context_cost_estimate"], (int, float))


def test_backlog_add_fails_loud_on_duplicates_and_unknown_deps(toy):
    proc = run_cli("backlog", "add", "--id", "slice-042",
                   "--acceptance", "tests/slices/042_orders.py", root=toy)
    assert proc.returncode == 1 and "slice-042" in proc.stderr
    proc = run_cli("backlog", "add", "--id", "slice-051",
                   "--declares", "ghost-module",
                   "--acceptance", "tests/slices/051_x.py", root=toy)
    assert proc.returncode == 1 and "ghost-module" in proc.stderr


def test_backlog_estimate_still_works_without_subcommand(toy):
    proc = run_cli("backlog", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "slices" in json.loads(proc.stdout)


# ---------------------------------------------------------------- imp-4
def test_merge_slice_finishes_the_mechanical_tail(toy):
    """The whole post-close ceremony in one command: merge the branch,
    regenerate+commit shadows, run the G4 safety net, remove worktree and
    branch."""
    wt = toy / ".worktrees" / "slice-042"
    assert git(toy, "worktree", "add", str(wt), "-b",
               "slice/slice-042").returncode == 0
    run_cli("slice", "--slice", "slice-042", "--session", "m4", root=wt)
    (wt / "orders.py").write_text(GOOD_ORDERS)
    run_cli("extract", str(wt / "orders.py"), root=wt)
    git(wt, "add", "-A")
    git(wt, "commit", "-qm", "slice-042 in worktree")
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", "m4",
                   "--commit", "HEAD", root=wt)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    proc = run_cli("merge-slice", "--slice", "slice-042", root=toy, env=NO_ENV)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["merged"] is True
    assert (toy / "orders.py").exists(), "slice work must land in main"
    rows = {r["id"]: r for r in read_jsonl(toy / ".harness" / "backlog.jsonl")}
    assert rows["slice-042"]["status"] == "closed"
    assert not wt.exists(), "worktree must be removed"
    assert git(toy, "rev-parse", "--verify",
               "slice/slice-042").returncode != 0, "branch must be deleted"
    assert not git(toy, "status", "--porcelain",
                   "--", ".harness").stdout.strip(), \
        "regenerated shadows must be committed, not left dirty"


def test_merge_slice_refuses_an_unclosed_slice(toy):
    wt = toy / ".worktrees" / "slice-042"
    git(toy, "worktree", "add", str(wt), "-b", "slice/slice-042")
    run_cli("slice", "--slice", "slice-042", "--session", "m5", root=wt)
    (wt / "orders.py").write_text(GOOD_ORDERS)
    git(wt, "add", "-A")
    git(wt, "commit", "-qm", "wip")
    proc = run_cli("merge-slice", "--slice", "slice-042", root=toy, env=NO_ENV)
    assert proc.returncode == 1
    assert "close" in (proc.stdout + proc.stderr).lower()
