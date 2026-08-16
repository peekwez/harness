"""Provenance notes are enforced, not best-effort: a slice cannot close
without recording where its work landed, a failed note write blocks instead
of warning, and CI catches any closed slice whose note is missing."""
import json

from conftest import build_toy_repo, git, loaded_context, make_event, run_cli
from engine import read_jsonl
from engine.events import handle_event

GOOD_ORDERS = ("import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
               "    telemetry.emit_span('create_order', {'sku': sku})\n"
               "    return {'sku': sku}\n")


def _ready(toy, session="notes"):
    run_cli("slice", "--slice", "slice-042", "--session", session, root=toy)
    loaded_context(toy, session=session)
    (toy / "orders.py").write_text(GOOD_ORDERS)
    handle_event(make_event("post_change", session=session,
                            files=["orders.py"]), toy)
    handle_event(make_event("unit_complete", session=session), toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "slice-042 work")
    return session


def _status(toy):
    return {r["id"]: r["status"] for r in
            read_jsonl(toy / ".harness" / "backlog.jsonl")}["slice-042"]


def test_close_without_a_commit_is_refused_in_a_git_repo(toy):
    """A slice IS a commit boundary — closing without one records no
    provenance at all, and used to succeed silently."""
    session = _ready(toy)
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   root=toy)
    assert proc.returncode == 1, proc.stdout
    out = json.loads(proc.stdout)
    assert not out["closed"]
    assert "--commit" in out["reason"]
    assert _status(toy) != "closed", "a refused close must not mutate status"
    # the named fix works
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["note_written"] is True


def test_a_failed_note_write_blocks_the_close(toy):
    """Provenance travelling with the repo is the whole claim: if the note
    cannot be written, the close is not done."""
    session = _ready(toy)
    lock = toy / ".git" / "refs" / "notes" / "harness.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("")                       # stale lock: git cannot update the ref
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 1, proc.stdout
    out = json.loads(proc.stdout)
    assert not out["closed"] and "note" in out["reason"].lower()
    assert _status(toy) != "closed"
    lock.unlink()
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_verify_flags_a_closed_slice_with_no_note(toy):
    session = _ready(toy)
    assert run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy).returncode == 0
    assert run_cli("verify", root=toy).returncode == 0

    # both keys must go: since ADR-002 / D-010 a note is keyed twice — on the
    # commit and in the derived .harness/notes.jsonl — and only a slice with
    # NEITHER is missing provenance (losing just the ref now resolves by tree
    # hash, which is the point of the second key)
    git(toy, "update-ref", "-d", "refs/notes/harness")     # provenance lost
    (toy / ".harness" / "notes.jsonl").unlink()
    proc = run_cli("verify", root=toy)
    assert proc.returncode == 1
    out = json.loads(proc.stdout)
    f = next(f for f in out["findings"] if f["code"] == "MISSING_PROVENANCE_NOTE")
    assert "slice-042" in f["message"]
    assert "graph note" in f["message"], "the repair command must be named"


def test_graph_note_repairs_missing_provenance(toy):
    session = _ready(toy)
    run_cli("close-slice", "--slice", "slice-042", "--session", session,
            "--commit", "HEAD", root=toy)
    git(toy, "update-ref", "-d", "refs/notes/harness")
    (toy / ".harness" / "notes.jsonl").unlink()          # D-010: both keys
    head = git(toy, "rev-parse", "HEAD").stdout.strip()
    proc = run_cli("graph", "note", "--slice", "slice-042", "--commit", head,
                   root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert run_cli("verify", root=toy).returncode == 0, "verify must recover"
    notes = git(toy, "notes", "--ref=refs/notes/harness", "list").stdout
    assert notes.strip()


def test_one_commit_can_carry_several_slices_provenance(toy):
    """A commit legitimately carries more than one slice (squash merges, a
    repair of historical closes) — `git notes add -f` overwrote, so only the
    last slice's provenance survived."""
    from engine.graph import read_notes, write_note
    head = git(toy, "rev-parse", "HEAD").stdout.strip()
    write_note(toy, head, {"slice_id": "slice-a", "modules_touched": ["a.py"]})
    write_note(toy, head, {"slice_id": "slice-b", "modules_touched": ["b.py"]})
    payloads = [p for n in read_notes(toy) for p in n["payloads"]]
    ids = {p["slice_id"] for p in payloads}
    assert ids == {"slice-a", "slice-b"}, ids
    # re-writing the same slice replaces its entry rather than duplicating
    write_note(toy, head, {"slice_id": "slice-a", "modules_touched": ["a2.py"]})
    payloads = [p for n in read_notes(toy) for p in n["payloads"]]
    assert len(payloads) == 2
    assert {"a2.py"} == set(next(p for p in payloads
                                 if p["slice_id"] == "slice-a")["modules_touched"])


def test_verify_accepts_a_commit_noting_every_closed_slice(toy):
    """The repair path for a repo whose history predates note enforcement."""
    session = _ready(toy)
    run_cli("close-slice", "--slice", "slice-042", "--session", session,
            "--commit", "HEAD", root=toy)
    git(toy, "update-ref", "-d", "refs/notes/harness")
    (toy / ".harness" / "notes.jsonl").unlink()          # D-010: both keys
    head = git(toy, "rev-parse", "HEAD").stdout.strip()
    # two historical slices, one commit
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows.append({**rows[0], "id": "slice-old", "status": "closed"})
    from engine import write_jsonl
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    for sid in ("slice-042", "slice-old"):
        assert run_cli("graph", "note", "--slice", sid, "--commit", head,
                       root=toy).returncode == 0
    proc = run_cli("verify", root=toy)
    assert proc.returncode == 0, proc.stdout


def test_close_still_works_without_git(tmp_path):
    """Notes are impossible outside a repo — enforcement must not brick
    substrate-only usage."""
    root = build_toy_repo(tmp_path / "nogit")
    import shutil
    shutil.rmtree(root / ".git")
    session = "nogit"
    run_cli("slice", "--slice", "slice-042", "--session", session, root=root)
    loaded_context(root, session=session)
    (root / "orders.py").write_text(GOOD_ORDERS)
    handle_event(make_event("post_change", session=session,
                            files=["orders.py"]), root)
    handle_event(make_event("unit_complete", session=session), root)
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   root=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["note_written"] is False
