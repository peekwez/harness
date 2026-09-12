"""Transactional guarantees for the local ``merge-slice`` ceremony."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import yaml

from conftest import git, run_cli


GOOD_ORDERS = ("import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
               "    telemetry.emit_span('create_order', {'sku': sku})\n"
               "    return {'sku': sku}\n")
NO_ENV = {"CLAUDE_SESSION_ID": ""}


def _closed_slice_worktree(toy):
    wt = toy / ".worktrees" / "slice-042"
    assert git(toy, "worktree", "add", str(wt), "-b",
               "slice/slice-042").returncode == 0
    bound = run_cli("slice", "--slice", "slice-042", "--session", "merge",
                    root=wt)
    assert bound.returncode == 0, bound.stdout + bound.stderr
    (wt / "orders.py").write_text(GOOD_ORDERS)
    assert run_cli("extract", str(wt / "orders.py"),
                   root=wt).returncode == 0
    git(wt, "add", "-A")
    assert git(wt, "commit", "-qm", "slice work").returncode == 0
    closed = run_cli("close-slice", "--slice", "slice-042",
                     "--session", "merge", "--commit", "HEAD", root=wt)
    assert closed.returncode == 0, closed.stdout + closed.stderr
    return wt


def _branch_exists(toy):
    return git(toy, "rev-parse", "--verify",
               "slice/slice-042").returncode == 0


def test_merge_refuses_dirty_tracked_index_and_worktree_without_changes(toy):
    wt = _closed_slice_worktree(toy)
    head = git(toy, "rev-parse", "HEAD").stdout.strip()
    telemetry = toy / "telemetry.py"
    telemetry.write_text("staged = True\n")
    git(toy, "add", "telemetry.py")
    telemetry.write_text("working = True\n")
    scratch = toy / "keep-untracked.txt"
    scratch.write_text("mine\n")
    staged_before = git(toy, "diff", "--cached", "--", "telemetry.py").stdout
    working_before = git(toy, "diff", "--", "telemetry.py").stdout

    proc = run_cli("merge-slice", "--slice", "slice-042", root=toy,
                   env=NO_ENV)

    assert proc.returncode == 1, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["merged"] is False and out["rolled_back"] is False
    assert "clean tracked" in out["reason"]
    assert git(toy, "rev-parse", "HEAD").stdout.strip() == head
    assert git(toy, "diff", "--cached", "--", "telemetry.py").stdout == staged_before
    assert git(toy, "diff", "--", "telemetry.py").stdout == working_before
    assert scratch.read_text() == "mine\n"
    assert wt.exists() and _branch_exists(toy)


def test_merge_loads_branch_config_and_rolls_back_its_gate_failure(toy):
    wt = _closed_slice_worktree(toy)
    config_path = wt / ".harness" / "config.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["acceptance"] = {"gate_cmd": "false"}
    config_path.write_text(yaml.safe_dump(config))
    git(wt, "add", ".harness/config.yaml")
    assert git(wt, "commit", "-qm", "branch requires failing gate").returncode == 0
    head = git(toy, "rev-parse", "HEAD").stdout.strip()
    scratch = toy / "keep-untracked.txt"
    scratch.write_text("mine\n")

    proc = run_cli("merge-slice", "--slice", "slice-042", root=toy,
                   env=NO_ENV)

    assert proc.returncode == 1, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["merged"] is False and out["rolled_back"] is True
    assert "ACCEPTANCE_GATE_FAILED" in json.dumps(out)
    assert git(toy, "rev-parse", "HEAD").stdout.strip() == head
    assert not (toy / "orders.py").exists()
    assert scratch.read_text() == "mine\n"
    assert wt.exists() and _branch_exists(toy)


def test_merge_rolls_back_when_postmerge_unit_complete_blocks(
        toy, monkeypatch, capsys):
    wt = _closed_slice_worktree(toy)
    head = git(toy, "rev-parse", "HEAD").stdout.strip()

    def blocked(*_args, **_kwargs):
        return {"verdict": "block", "findings": [{
            "code": "POSTMERGE_BLOCK", "rule_ref": "gate:G5",
            "message": "merged graph is invalid",
        }]}

    import engine.events
    monkeypatch.setattr(engine.events, "handle_event", blocked)
    from engine.cli.close import cmd_merge_slice

    rc = cmd_merge_slice(SimpleNamespace(
        root=str(toy), slice="slice-042", session=None))
    out = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert out["merged"] is False and out["rolled_back"] is True
    assert out["gates"] == "block"
    assert "POSTMERGE_BLOCK" in json.dumps(out)
    assert git(toy, "rev-parse", "HEAD").stdout.strip() == head
    assert not (toy / "orders.py").exists()
    assert wt.exists() and _branch_exists(toy)


def test_merge_rolls_back_when_substrate_commit_hook_fails(toy):
    wt = _closed_slice_worktree(toy)
    head = git(toy, "rev-parse", "HEAD").stdout.strip()
    hook = toy / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)

    proc = run_cli("merge-slice", "--slice", "slice-042", root=toy,
                   env=NO_ENV)

    assert proc.returncode == 1, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["merged"] is False and out["rolled_back"] is True
    assert "substrate" in out["reason"] and "commit" in out["reason"]
    assert git(toy, "rev-parse", "HEAD").stdout.strip() == head
    assert not (toy / "orders.py").exists()
    assert not git(toy, "status", "--short",
                   "--untracked-files=no").stdout.strip()
    assert wt.exists() and _branch_exists(toy)


def test_merge_rolls_back_when_successful_gate_mutates_tracked_source(toy):
    wt = _closed_slice_worktree(toy)
    config_path = toy / ".harness" / "config.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["acceptance"] = {
        "gate_cmd": (f"{sys.executable} -c \"from pathlib import Path; "
                     "Path('orders.py').write_text('broken = True\\n')\"")}
    config_path.write_text(yaml.safe_dump(config))
    git(toy, "add", ".harness/config.yaml")
    assert git(toy, "commit", "-qm", "mutating gate").returncode == 0
    head = git(toy, "rev-parse", "HEAD").stdout.strip()
    scratch = toy / "keep-untracked.txt"
    scratch.write_text("mine\n")

    proc = run_cli("merge-slice", "--slice", "slice-042", root=toy,
                   env=NO_ENV)

    assert proc.returncode == 1, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["merged"] is False and out["rolled_back"] is True
    assert "tracked source" in out["reason"]
    assert git(toy, "rev-parse", "HEAD").stdout.strip() == head
    assert not (toy / "orders.py").exists()
    assert scratch.read_text() == "mine\n"
    assert wt.exists() and _branch_exists(toy)


def test_merge_rolls_back_when_extraction_raises(toy, monkeypatch, capsys):
    wt = _closed_slice_worktree(toy)
    head = git(toy, "rev-parse", "HEAD").stdout.strip()
    from engine.extractor import engine as extractor
    monkeypatch.setattr(
        extractor, "extract_all",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("extract boom")))
    from engine.cli.close import cmd_merge_slice

    rc = cmd_merge_slice(SimpleNamespace(
        root=str(toy), slice="slice-042", session=None))
    out = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert out["merged"] is False and out["rolled_back"] is True
    assert "extract" in out["reason"] and "extract boom" in out["reason"]
    assert git(toy, "rev-parse", "HEAD").stdout.strip() == head
    assert not (toy / "orders.py").exists()
    assert wt.exists() and _branch_exists(toy)


def test_merge_rolls_back_when_event_pipeline_raises(toy, monkeypatch, capsys):
    wt = _closed_slice_worktree(toy)
    head = git(toy, "rev-parse", "HEAD").stdout.strip()
    import engine.events
    monkeypatch.setattr(
        engine.events, "handle_event",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("event boom")))
    from engine.cli.close import cmd_merge_slice

    rc = cmd_merge_slice(SimpleNamespace(
        root=str(toy), slice="slice-042", session=None))
    out = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert out["merged"] is False and out["rolled_back"] is True
    assert "event" in out["reason"] and "event boom" in out["reason"]
    assert git(toy, "rev-parse", "HEAD").stdout.strip() == head
    assert not (toy / "orders.py").exists()
    assert wt.exists() and _branch_exists(toy)
