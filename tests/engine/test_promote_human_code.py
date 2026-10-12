"""0.10.4: a human types a code at a terminal for each shared-memory write."""
import json
import re

import pytest

from conftest import run_cli, run_cli_as_human
from engine import HarnessError, human
from engine import shared_memory as sm

FACT = ".claude/memory/shared/deploys-happen-on-tuesdays.md"
LEDGER = ".harness/promotions.jsonl"


def _ledger_rows(toy):
    path = toy / LEDGER
    return path.read_text().splitlines() if path.exists() else []


def test_promote_without_a_terminal_writes_nothing(toy):
    proc = run_cli("memory", "promote", "--text", "Deploys happen on Tuesdays.",
                   root=toy)
    assert proc.returncode == 1
    error = json.loads(proc.stderr)["error"]
    assert "a human must approve this at a terminal" in error
    assert "run the same command yourself in your own terminal" in error
    assert not (toy / FACT).exists()
    assert _ledger_rows(toy) == []


def test_accept_without_a_terminal_writes_nothing(toy):
    shared = toy / ".claude/memory/shared"
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "x.md").write_text("A human wrote this.\n")
    proc = run_cli("memory", "accept", ".claude/memory/shared/x.md", root=toy)
    assert proc.returncode == 1
    assert "a human must approve this at a terminal" in json.loads(proc.stderr)["error"]
    assert _ledger_rows(toy) == []


def test_the_typed_code_writes_and_the_terminal_shows_the_fact(toy):
    proc = run_cli_as_human("memory", "promote", "--text",
                            "Deploys happen on Tuesdays.", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["promoted"] is True
    assert "will write " + FACT in proc.terminal
    assert "Deploys happen on Tuesdays." in proc.terminal
    assert (toy / FACT).exists()
    assert any(FACT in row for row in _ledger_rows(toy))


def test_a_wrong_code_writes_nothing(toy):
    proc = run_cli_as_human("memory", "promote", "--text",
                            "Deploys happen on Tuesdays.", root=toy,
                            answer="NOPE")
    assert proc.returncode == 1
    assert "the code did not match" in json.loads(proc.stderr)["error"]
    assert not (toy / FACT).exists()
    assert _ledger_rows(toy) == []


def test_the_code_never_reaches_stdout_or_stderr(toy):
    proc = run_cli_as_human("memory", "promote", "--text",
                            "Deploys happen on Tuesdays.", root=toy,
                            answer="NOPE")
    code = re.search(r"type ([A-Z0-9]+) and press Enter", proc.terminal).group(1)
    assert code not in proc.stdout and code not in proc.stderr


def test_accept_needs_the_code_too(toy):
    shared = toy / ".claude/memory/shared"
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "x.md").write_text("A human wrote this.\n")
    wrong = run_cli_as_human("memory", "accept", ".claude/memory/shared/x.md",
                             root=toy, answer="")
    assert wrong.returncode == 1
    assert _ledger_rows(toy) == []
    right = run_cli_as_human("memory", "accept", ".claude/memory/shared/x.md",
                             root=toy)
    assert right.returncode == 0, right.stdout + right.stderr
    assert "current content of .claude/memory/shared/x.md" in right.terminal
    assert len(_ledger_rows(toy)) == 1


def test_a_bad_request_fails_before_the_prompt(toy):
    proc = run_cli_as_human("memory", "promote", root=toy)
    assert proc.returncode == 2
    assert "press Enter" not in proc.terminal


def test_confirm_refuses_without_a_terminal(tmp_path):
    with pytest.raises(HarnessError, match="has none"):
        human.confirm("memory promote", "x", tty=str(tmp_path / "no-tty"))


def test_codes_are_random_and_unambiguous():
    codes = {human.new_code() for _ in range(200)}
    assert len(codes) > 150
    assert all(len(c) == 4 and not set(c) & set("0O1IL2Z5S8B") for c in codes)


def test_in_process_promote_asks_the_human_first(toy, monkeypatch):
    def refuse(action, summary, **_):
        raise HarnessError(f"{action}: refused")
    monkeypatch.setattr(human, "confirm", refuse)
    with pytest.raises(HarnessError, match="refused"):
        sm.promote(toy, text="Deploys happen on Tuesdays.")
    assert not (toy / FACT).exists()
    assert _ledger_rows(toy) == []
