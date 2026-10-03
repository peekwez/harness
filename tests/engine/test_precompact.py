"""PreCompact: reset the context hashes and count the compaction (7.4, D-0.10-11)."""
import argparse
import json

from conftest import make_event, run_cli
from engine.events import handle_event


def test_precompact_resets_context_so_next_prompt_injects_again(toy):
    first = handle_event(make_event("session_start", session="pc"), toy)
    assert first["injections"]
    quiet = handle_event(make_event("pre_context", session="pc"), toy)
    assert quiet["injections"] == []
    proc = run_cli("precompact", "--session", "pc", root=toy)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["compaction_recorded"] is True
    again = handle_event(make_event("pre_context", session="pc"), toy)
    assert again["injections"]


def test_precompact_emits_compaction_reached(toy):
    events = toy / ".harness" / "cache" / "events.jsonl"
    before = events.read_text() if events.exists() else ""
    assert run_cli("precompact", "--session", "pc2", root=toy).returncode == 0
    after = events.read_text()
    assert "COMPACTION_REACHED" in after and "COMPACTION_REACHED" not in before


def test_failed_clear_still_records_compaction_and_fails(toy, monkeypatch, capsys):
    from engine.cli.substrate import cmd_precompact
    from engine.events import Sidecar

    def boom(self, session):
        raise RuntimeError("clear exploded")

    monkeypatch.setattr(Sidecar, "block_hashes_clear", boom)
    events = toy / ".harness" / "cache" / "events.jsonl"
    before = events.read_text() if events.exists() else ""
    code = cmd_precompact(argparse.Namespace(root=str(toy), session="pc3"))
    assert code == 1
    assert "clear exploded" in capsys.readouterr().err
    after = events.read_text()
    assert "COMPACTION_REACHED" in after and "COMPACTION_REACHED" not in before
