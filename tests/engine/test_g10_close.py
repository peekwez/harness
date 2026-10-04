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


# ---------------------------------------------- ledger merge rule (6c ruling)
LEDGER = ".harness/promotions.jsonl"
UNION_LINE = f"{LEDGER} merge=union"


def test_ledger_is_a_union_merge_path():
    from engine.cli.common import SUBSTRATE_UNION_MERGE
    assert LEDGER in SUBSTRATE_UNION_MERGE


def test_init_writes_the_ledger_merge_rule(tmp_path):
    root = tmp_path / "fresh"
    root.mkdir()
    git(root, "init", "-q")
    proc = run_cli("init", root=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert UNION_LINE in (root / ".gitattributes").read_text().splitlines()


def test_upgrade_adds_the_ledger_merge_rule(tmp_path):
    from conftest import build_legacy_08_repo
    root = build_legacy_08_repo(tmp_path / "legacy08")
    assert UNION_LINE not in (root / ".gitattributes").read_text()
    run_cli("upgrade", "--yes", root=root)
    assert UNION_LINE in (root / ".gitattributes").read_text().splitlines()


def test_stale_merge_rules_keep_the_ledger_rule(tmp_path):
    from engine.upgrade_w8 import STEP
    root = tmp_path / "r"
    root.mkdir()
    (root / ".gitattributes").write_text(UNION_LINE + "\n")
    assert STEP.describe(root) == []


def test_two_branches_promote_and_the_ledger_merges(toy):
    from engine.cli.common import _install_merge_drivers
    from engine import read_jsonl
    _install_merge_drivers(toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "merge rules")
    git(toy, "checkout", "-qb", "a")
    run_cli("memory", "promote", "--text", "Deploys happen on Tuesdays.",
            "--name", "deploys", root=toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "promote a")
    git(toy, "checkout", "-q", "-")
    git(toy, "checkout", "-qb", "b")
    run_cli("memory", "promote", "--text", "Tests run with pytest.",
            "--name", "pytest", root=toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "promote b")
    git(toy, "merge", "-q", "--no-edit", "a")
    conflicted = git(toy, "diff", "--name-only", "--diff-filter=U").stdout.split()
    assert LEDGER not in conflicted, conflicted
    paths = [r["path"] for r in read_jsonl(toy / LEDGER)]
    assert ".claude/memory/shared/deploys.md" in paths
    assert ".claude/memory/shared/pytest.md" in paths
