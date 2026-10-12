"""0.10.5: G10 at close trusts this machine's approval store, not the
ledger an agent can append to."""
import hashlib
import json

import pytest

from conftest import git, make_event, run_cli_as_human
from engine import HarnessError, approvals
from engine import shared_memory as sm
from engine.events import handle_event
from test_g10_close import FACT, _close, _g10, _start

LEDGER = ".harness/promotions.jsonl"


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def test_the_store_ignores_home_and_xdg(monkeypatch, tmp_path):
    monkeypatch.setattr(approvals, "_STORE_OVERRIDE", None)
    real = approvals.store_path()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert approvals.store_path() == real
    assert real.parts[-3:] == (".config", "harness", "approvals.jsonl")
    assert not str(real).startswith(str(tmp_path))


def test_a_forged_ledger_row_does_not_pass_close(toy):
    session = _start(toy)
    body = "Deploys happen on Tuesdays.\n"
    (toy / FACT).parent.mkdir(parents=True)
    (toy / FACT).write_text(body)                       # a shell write
    with open(toy / LEDGER, "a") as ledger:             # and a forged row
        ledger.write(json.dumps({"path": FACT, "sha256": _sha(body),
                                 "at": "2026-10-11T00:00:00+00:00"}) + "\n")
    assert sm.sanctioned(toy, FACT)                     # the ledger agrees
    proc, out = _close(toy, session)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert [f for f in _g10(out) if FACT in f["message"]]


def test_promote_records_each_write_in_the_store(toy, approval_store):
    proc = run_cli_as_human("memory", "promote", "--text",
                            "Deploys happen on Tuesdays.", "--name", "deploys",
                            root=toy)
    assert proc.returncode == 0, proc.stderr
    rows = [json.loads(l) for l in approval_store.read_text().splitlines()]
    paths = {r["path"] for r in rows}
    assert {FACT, ".claude/memory/shared/MEMORY.md"} <= paths
    assert all(r["repo"] == approvals.repo_key(toy) and r["by"] for r in rows)
    assert sm.approved_here(toy, FACT)


def test_an_unwritable_store_refuses_before_any_write(toy, monkeypatch,
                                                     tmp_path, human_approves):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monkeypatch.setattr(approvals, "_STORE_OVERRIDE", blocker / "approvals.jsonl")
    with pytest.raises(HarnessError, match="cannot write the approval store"):
        sm.promote(toy, text="Deploys happen on Tuesdays.", name="deploys")
    assert not (toy / FACT).exists()
    assert not (toy / LEDGER).exists() or FACT not in (toy / LEDGER).read_text()


def test_an_approval_for_another_repo_does_not_count(toy, approval_store):
    body = "Deploys happen on Tuesdays.\n"
    (toy / FACT).parent.mkdir(parents=True)
    (toy / FACT).write_text(body)
    approval_store.write_text(json.dumps(
        {"repo": "/some/other/repo", "path": FACT, "sha256": _sha(body),
         "at": "x", "by": "x"}) + "\n")
    assert not sm.approved_here(toy, FACT)


def test_accept_at_the_terminal_lets_close_pass(toy):
    session = _start(toy)
    (toy / FACT).parent.mkdir(parents=True)
    (toy / FACT).write_text("A human typed this.\n")
    accepted = run_cli_as_human("memory", "accept", FACT, root=toy)
    assert accepted.returncode == 0, accepted.stderr
    proc, out = _close(toy, session)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_an_accepted_deletion_passes_and_a_forged_one_does_not(toy):
    run_cli_as_human("memory", "promote", "--text", "Deploys happen on Tuesdays.",
                     "--name", "deploys", root=toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "promote before the slice")
    (toy / FACT).unlink()
    with open(toy / LEDGER, "a") as ledger:
        ledger.write(json.dumps({"path": FACT, "sha256": None,
                                 "deleted": True, "at": "x"}) + "\n")
    assert not sm.approved_here(toy, FACT)
    run_cli_as_human("memory", "accept", FACT, root=toy)
    assert sm.approved_here(toy, FACT)


@pytest.mark.parametrize("rel", [LEDGER, "./.harness/promotions.jsonl",
                                 ".HARNESS/Promotions.jsonl"])
def test_a_tool_edit_to_the_ledger_is_blocked(toy, rel):
    v = handle_event(make_event("pre_change", session="g10l", files=[rel]), toy)
    assert v["verdict"] == "block"
    [finding] = [f for f in v["findings"] if f["code"] == "SHARED_MEMORY_WRITE"]
    assert "own terminal" in finding["fix"]
    assert len(finding["message"].split()) <= 25
