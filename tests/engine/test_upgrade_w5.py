"""W5 upgrade step (spec 12 step 9): in-flight slices become legacy."""
import json

from conftest import build_toy_repo, git, loaded_context, make_event, run_cli
from engine import get_slice, load_backlog, save_slice
from engine.events import handle_event

GOOD_ORDERS = ("import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
               "    telemetry.emit_span('create_order', {'sku': sku})\n"
               "    return {'sku': sku}\n")


def _step():
    from engine.upgrade_010 import STEPS
    return next(s for s in STEPS if s.id == "w5.legacy-verification")


def _yes(_question):
    return True


def _old_repo(tmp_path):
    """A 0.9-style backlog: rows have neither verifies nor the flag."""
    toy = build_toy_repo(tmp_path / "toy", legacy_verification=None)
    sl = get_slice(toy, "slice-042")
    sl["status"] = "in_progress"
    save_slice(toy, sl)
    closed = dict(sl, id="slice-041", status="closed")
    save_slice(toy, closed)
    return toy


def test_step_is_registered_and_not_destructive():
    step = _step()
    assert step.destructive is False
    assert step.title


def test_describe_lists_non_closed_slices(tmp_path):
    toy = _old_repo(tmp_path)
    changes = _step().describe(toy)
    assert len(changes) == 1 and "slice-042" in changes[0]


def test_apply_marks_them_and_is_idempotent(tmp_path):
    toy = _old_repo(tmp_path)
    report = _step().apply(toy, _yes)
    assert any("slice-042" in line for line in report)
    rows = {r["id"]: r for r in load_backlog(toy)}
    assert rows["slice-042"]["legacy_verification"] is True
    assert "legacy_verification" not in rows["slice-041"]
    assert _step().describe(toy) == []
    assert _step().apply(toy, _yes) == []


def test_rerun_never_marks_slices_written_by_backlog_add(tmp_path):
    toy = _old_repo(tmp_path)
    _step().apply(toy, _yes)
    proc = run_cli("backlog", "add", "--id", "slice-050", "--acceptance",
                   "tests/slices/050_x.py", root=toy)
    assert proc.returncode == 0, proc.stderr
    assert _step().describe(toy) == []
    assert "legacy_verification" not in get_slice(toy, "slice-050")


def test_the_in_flight_slice_closes_without_a_red_record(tmp_path):
    toy = _old_repo(tmp_path)
    _step().apply(toy, _yes)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "upgrade")
    session = "up"
    assert run_cli("start", "--slice", "slice-042", "--session", session,
                   "--no-worktree", root=toy).returncode == 0
    loaded_context(toy, session=session)
    (toy / "orders.py").write_text(GOOD_ORDERS)
    handle_event(make_event("post_change", session=session,
                            files=["orders.py"]), toy)
    handle_event(make_event("unit_complete", session=session), toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "slice-042 work")
    proc = run_cli("close-slice", "--slice", "slice-042", "--session",
                   session, "--commit", "HEAD", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["verification"]["legacy"] is True
    assert not (toy / ".harness" / "verification" / "slice-042.json").exists()


def test_advise_names_each_worktree_with_a_backlog(tmp_path):
    from engine.upgrade_w5 import advise
    toy = _old_repo(tmp_path)
    assert advise(toy) == []
    wt = toy / ".worktrees" / "slice-042"
    (wt / ".harness").mkdir(parents=True)
    (wt / ".harness" / "backlog.jsonl").write_text("")
    (toy / ".worktrees" / "stray").mkdir()
    lines = advise(toy)
    assert lines == ["check: run harness upgrade in .worktrees/slice-042 to "
                     "mark its in-flight slice legacy."]
    assert not any(c.startswith("check:") for c in _step().describe(toy))
