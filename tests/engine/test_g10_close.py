"""G10 at close (W8-P21): a shell write to shared memory rides the slice
diff, so close checks the slice change set. `harness memory promote` is
the only sanctioned writer; its ledger rows name the bytes it wrote."""
import json

from conftest import build_toy_repo, git, loaded_context, make_event, run_cli
from engine.events import handle_event

FACT = ".claude/memory/shared/deploys.md"
GOOD_ORDERS = ("import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
               "    telemetry.emit_span('create_order', {'sku': sku})\n"
               "    return {'sku': sku}\n")


def _start(toy, session="g10c"):
    run_cli("start", "--slice", "slice-042", "--session", session,
            "--no-worktree", root=toy)
    loaded_context(toy, session=session)
    (toy / "orders.py").write_text(GOOD_ORDERS)
    handle_event(make_event("post_change", session=session,
                            files=["orders.py"]), toy)
    return session


def _close(toy, session):
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "slice-042 work")
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    return proc, json.loads(proc.stdout or "{}")


def _g10(out):
    return [f for f in out.get("findings", [])
            if f.get("code") == "SHARED_MEMORY_WRITE"]


def test_shell_write_to_shared_memory_blocks_close(toy):
    session = _start(toy)
    (toy / FACT).parent.mkdir(parents=True)
    (toy / FACT).write_text("Deploys happen on Tuesdays.\n")  # a shell write
    proc, out = _close(toy, session)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    [finding] = _g10(out)
    assert finding["rule_ref"] == "gate:G10"
    assert finding["severity"] == "block"
    assert FACT in finding["message"]
    assert len(finding["message"].split()) <= 25
    assert "harness memory promote" in finding["fix"]
    assert "revert" in finding["fix"].lower()


def test_promoted_fact_on_the_slice_closes(toy):
    session = _start(toy)
    promoted = run_cli("memory", "promote", "--text",
                       "Deploys happen on Tuesdays.", "--name", "deploys",
                       root=toy)
    assert promoted.returncode == 0, promoted.stderr
    proc, out = _close(toy, session)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert out["closed"] is True


def test_shell_edit_after_promote_blocks_close(toy):
    session = _start(toy)
    run_cli("memory", "promote", "--text", "Deploys happen on Tuesdays.",
            "--name", "deploys", root=toy)
    with open(toy / FACT, "a") as fh:
        fh.write("Also Thursdays.\n")
    proc, out = _close(toy, session)
    assert proc.returncode == 1, proc.stdout
    assert [f for f in _g10(out) if FACT in f["message"]]


def test_deleted_shared_memory_file_blocks_close(toy):
    run_cli("memory", "promote", "--text", "Deploys happen on Tuesdays.",
            "--name", "deploys", root=toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "promote before the slice")
    session = _start(toy)
    (toy / FACT).unlink()
    proc, out = _close(toy, session)
    assert proc.returncode == 1, proc.stdout
    [finding] = _g10(out)
    assert FACT in finding["message"]


def test_unrelated_slice_has_no_g10_finding(toy):
    run_cli("memory", "promote", "--text", "Deploys happen on Tuesdays.",
            "--name", "deploys", root=toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "promote before the slice")
    session = _start(toy)
    proc, out = _close(toy, session)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not _g10(out)


def test_legacy_repo_without_shared_memory_closes(tmp_path):
    toy = build_toy_repo(tmp_path / "legacy")
    session = _start(toy)
    proc, out = _close(toy, session)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not (toy / ".claude/memory/shared").exists()


def test_g10_runs_at_unit_complete_and_keeps_pre_change():
    from engine.gates import gates_for_event
    assert "G10" in {g.GATE["id"] for g in gates_for_event("unit_complete")}
    assert "G10" in {g.GATE["id"] for g in gates_for_event("pre_change")}


def test_unit_complete_without_files_is_quiet(toy):
    (toy / FACT).parent.mkdir(parents=True)
    (toy / FACT).write_text("x\n")
    v = handle_event(make_event("unit_complete", session="g10u"), toy)
    assert not [f for f in v["findings"] if f["code"] == "SHARED_MEMORY_WRITE"]


def test_promote_records_the_bytes_it_wrote(toy):
    from engine.shared_memory import sanctioned
    run_cli("memory", "promote", "--text", "Deploys happen on Tuesdays.",
            "--name", "deploys", root=toy)
    assert sanctioned(toy, FACT)
    assert sanctioned(toy, ".claude/memory/shared/MEMORY.md")
    (toy / FACT).write_text("forged\n")
    assert not sanctioned(toy, FACT)
    assert not sanctioned(toy, ".claude/memory/shared/other.md")
