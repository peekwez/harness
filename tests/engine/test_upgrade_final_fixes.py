"""W8 final-review fixes: the 0.9 `--plugin` parent, the index, reruns,
Claude and Codex settings, line endings and the JSONL readers."""
from __future__ import annotations

import io
import json
import os
import pty
import shutil
import stat
import subprocess
import sys

import pytest

from conftest import (HARNESS_BIN, PLUGIN_ROOT, build_astralabs_094_repo,
                      build_legacy_08_repo, build_toy_repo, git, run_cli)

INDEX_DELETIONS = (".harness/shadows/", ".harness/memory/")


def _upgrade(root, *args):
    proc = run_cli("upgrade", "--yes", *args, root=root)
    assert proc.stdout.strip(), proc.stderr
    return proc, json.loads(proc.stdout)


def _run_commit(out):
    commit = out["commit"]
    done = subprocess.run(["bash", "-c", commit["command"]], cwd=commit["cwd"],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def _staged_before_lines(out):
    return [h for h in out["human_checks"] if "before the upgrade" in h]


# ------------------------------------------------------------ 1. --plugin
class _Tty(io.StringIO):
    def isatty(self):
        return True


def test_tty_ask_answers_no_when_stderr_is_not_a_terminal(monkeypatch):
    """A 0.9 parent captures stderr: the prompt would be invisible."""
    from engine import upgrade_010

    class NoRead(_Tty):
        def readline(self, *args):
            raise AssertionError("read stdin")
    monkeypatch.setattr("sys.stdin", NoRead("y\n"))
    monkeypatch.setattr("sys.stderr", io.StringIO())
    assert upgrade_010.tty_ask("Delete it?") is False


def test_make_ask_answers_no_when_stderr_is_not_a_terminal():
    from engine.upgrade_report import make_ask
    assert make_ask(False, stdin=_Tty("y\n"), stderr=io.StringIO())("Delete?") is False


def test_child_with_a_terminal_stdin_and_a_piped_stderr_never_waits(tmp_path):
    """What a 0.9.4 parent does: capture stdout and stderr, inherit stdin."""
    root = build_astralabs_094_repo(tmp_path / "repo")
    leader, follower = pty.openpty()
    try:
        proc = subprocess.run([sys.executable, str(HARNESS_BIN), "--root", str(root),
                               "upgrade"], stdin=follower, capture_output=True,
                              text=True, timeout=120)
    finally:
        os.close(leader)
        os.close(follower)
    assert proc.returncode == 1
    assert "[y/N]" not in proc.stderr
    assert json.loads(proc.stdout)["status"] == "incomplete"


FAKE_CLAUDE = """#!/usr/bin/env python3
import json, sys
if sys.argv[1:4] == ["plugin", "list", "--json"]:
    print(json.dumps([{"id": "harness@team", "version": "0.10.0", "scope": "user",
                       "installPath": %r}]))
sys.exit(0)
"""


def test_the_094_parent_reports_an_incomplete_upgrade_and_never_hangs(tmp_path):
    """The real 0.9.4 `upgrade --plugin` against this engine, with a fake host
    CLI and a terminal on stdin: no prompt, no hang, a "command failed" error
    that holds the report. The two-step path then finishes the upgrade."""
    old = tmp_path / "engine-094"
    old.mkdir()
    # an export, not a worktree: the repository's git metadata stays untouched
    tar = subprocess.run(["git", "-C", str(PLUGIN_ROOT), "archive", "9492840"],
                         capture_output=True)
    if tar.returncode:
        pytest.skip(f"cannot read 0.9.4: {tar.stderr.decode().strip()}")
    subprocess.run(["tar", "-x", "-C", str(old)], input=tar.stdout, check=True)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "claude"
    fake.write_text(FAKE_CLAUDE % str(PLUGIN_ROOT))
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    root = build_astralabs_094_repo(tmp_path / "repo")
    env = dict(os.environ, PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}")
    leader, follower = pty.openpty()
    try:
        proc = subprocess.run(
            [sys.executable, str(old / "bin" / "harness"), "--root", str(root),
             "upgrade", "--plugin", "--host", "claude"],
            stdin=follower, capture_output=True, text=True, timeout=180, env=env)
    finally:
        os.close(leader)
        os.close(follower)
    assert proc.returncode != 0
    error = json.loads(proc.stderr)["error"]
    assert error.startswith("command failed")
    assert '"status": "incomplete"' in error
    # step two of docs/upgrading.md: the new engine, with --yes
    proc, out = _upgrade(root)
    assert out["status"] == "upgraded", out["failures"]


# ------------------------------------------------------------ 2. index
def test_pre_staged_human_work_blocks_the_commit_proposal(tmp_path):
    root = build_legacy_08_repo(tmp_path / "repo")
    (root / "human staged.txt").write_text("wip\n")
    (root / "orders.py").write_text((root / "orders.py").read_text() + "# wip\n")
    git(root, "add", "human staged.txt", "orders.py")
    proc, out = _upgrade(root)
    assert proc.returncode == 1
    assert out["status"] == "checks failed"
    assert out["commit"] is None
    [line] = [h for h in out["human_checks"] if "upgrade did not make" in h]
    assert "human staged.txt" in line and "orders.py" in line
    assert line.endswith("Commit or unstage them, then run: harness upgrade")
    assert len(line.split()) <= 25
    # unstage the human's work: the rerun proposes the upgrade alone
    git(root, "restore", "--staged", "--", "human staged.txt", "orders.py")
    proc, out = _upgrade(root)
    assert out["status"] == "upgraded", out["human_checks"]
    assert not {"human staged.txt", "orders.py"} & set(out["commit"]["paths"])
    _run_commit(out)
    shown = set(git(root, "show", "--name-only", "--format=", "HEAD").stdout.split("\n"))
    assert not {"human staged.txt", "orders.py"} & shown
    assert git(root, "diff", "--cached", "--name-only").stdout == ""


def test_the_upgrades_own_index_deletions_are_not_human_work(tmp_path):
    from engine import upgrade_report as rep
    root = build_astralabs_094_repo(tmp_path / "repo")
    proc, out = _upgrade(root)
    assert out["status"] == "upgraded"
    staged = rep.staged_paths(root)
    assert any(p.startswith(INDEX_DELETIONS) for p in staged)
    assert rep.foreign_staged(root, out["files"]) == []


# ------------------------------------------------------------ 3 + 4. reruns
def test_a_rerun_before_committing_proposes_the_same_commit(tmp_path):
    root = build_astralabs_094_repo(tmp_path / "repo")
    proc, first = _upgrade(root)
    assert first["status"] == "upgraded"
    proc, again = _upgrade(root)
    assert proc.returncode == 0
    assert again["status"] == "upgraded"
    assert again["commit"]["command"] == first["commit"]["command"]
    assert _staged_before_lines(again) == []
    assert not any("uncommitted edits" in h for h in again["human_checks"])
    _run_commit(again)
    assert git(root, "status", "--porcelain").stdout == ""
    proc, done = _upgrade(root)
    assert done["status"] == "already on 0.10"
    assert done["commit"] is None


def test_a_rerun_repeats_the_warning_for_mixed_human_edits(tmp_path):
    root = build_astralabs_094_repo(tmp_path / "repo")
    config = root / ".harness/config.yaml"
    config.write_text(config.read_text() + "# my edit\n")

    def warned(out):
        return any("uncommitted edits" in h and ".harness/config.yaml" in h
                   for h in out["human_checks"])
    proc, first = _upgrade(root)
    assert first["status"] == "upgraded" and warned(first)
    proc, again = _upgrade(root)
    assert again["status"] == "upgraded" and warned(again)
    assert again["commit"] == first["commit"]


def test_a_rerun_after_a_failed_stage_has_no_false_staged_check(tmp_path):
    root = build_astralabs_094_repo(tmp_path / "repo")
    (root / ".codex").mkdir()
    hooks = root / ".codex/hooks.json"
    hooks.write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [
        {"type": "command",
         "command": "python3 /old/harness/adapters/codex/adapter.py"}]}]}}))
    git(root, "add", "-A")
    git(root, "commit", "-qm", "codex")
    hooks.chmod(0o444)
    try:
        proc, first = _upgrade(root)
    finally:
        hooks.chmod(0o644)
    assert first["status"] == "failed"
    proc, out = _upgrade(root)
    assert out["status"] == "upgraded", out["failures"]
    assert _staged_before_lines(out) == []
    _run_commit(out)
    assert git(root, "status", "--porcelain").stdout == ""


def test_staged_before_ignores_the_upgrades_own_deletions_without_a_record(tmp_path):
    from engine import upgrade_report as rep
    root = build_astralabs_094_repo(tmp_path / "repo")
    git(root, "rm", "-r", "-q", "--cached", ".harness/shadows")
    shutil.rmtree(root / ".harness/shadows")
    (root / "human.txt").write_text("x\n")
    git(root, "add", "human.txt")
    assert rep.staged_before(root, {}) == ["human.txt"]


# ------------------------------------------------------------ 5. settings
def _add_permission(path, rule):
    data = json.loads(path.read_text())
    data["permissions"]["allow"].append(rule)
    path.write_text(json.dumps(data, indent=2) + "\n")


def test_a_human_rule_in_settings_json_is_backed_up_with_a_check(tmp_path):
    root = build_astralabs_094_repo(tmp_path / "repo")
    _add_permission(root / ".claude/settings.json", "Bash(make deploy-docs)")
    git(root, "commit", "-qam", "human rule")
    proc, out = _upgrade(root)
    assert out["status"] == "upgraded", out["failures"]
    backup = root / ".harness/cache/settings.json.pre-0.10"
    assert "Bash(make deploy-docs)" in backup.read_text()
    [line] = [h for h in out["human_checks"] if "settings.json.pre-0.10" in h]
    assert ".claude/settings.json" in line and "gitignored" in line
    assert len(line.split()) <= 25


def test_an_unedited_094_profile_needs_no_backup(tmp_path):
    root = build_astralabs_094_repo(tmp_path / "repo")
    proc, out = _upgrade(root)
    assert out["claude"]["settings"]["action"] == "refreshed"
    assert not (root / ".harness/cache/settings.json.pre-0.10").exists()
    assert not any("pre-0.10" in h and "settings" in h for h in out["human_checks"])


def test_settings_local_keeps_human_rules_in_place(tmp_path):
    root = build_astralabs_094_repo(tmp_path / "repo")
    local = root / ".claude/settings.local.json"
    data = json.loads((root / ".claude/settings.json").read_text())
    data["permissions"]["allow"].append("Bash(npm run e2e:*)")
    data["permissions"]["deny"].append("Bash(rm -rf:*)")
    data["env"] = {"FOO": "1"}
    local.write_text(json.dumps(data, indent=2) + "\n")
    proc, out = _upgrade(root)
    assert out["claude"]["settings_local"]["action"] == "refreshed"
    after = json.loads(local.read_text())
    assert "Bash(npm run e2e:*)" in after["permissions"]["allow"]
    assert "Bash(rm -rf:*)" in after["permissions"]["deny"]
    assert after["env"] == {"FOO": "1"}
    # the harness-owned keys are the 0.10 ones
    assert "Bash(*/bin/harness memory promote:*)" in after["permissions"]["ask"]
    assert "harness autonomy profile" in after["_comment"]
    assert not (root / ".harness/cache/settings.local.json.pre-0.10").exists()


def test_a_changed_codex_hooks_file_is_backed_up_with_a_check(tmp_path):
    root = build_astralabs_094_repo(tmp_path / "repo")
    (root / ".codex").mkdir()
    old = json.dumps({"hooks": {"PreToolUse": [{"hooks": [
        {"type": "command", "command": "python3 /old/harness/adapters/codex/adapter.py"},
        {"type": "command", "command": "./my-own-hook.sh"}]}]}})
    (root / ".codex/hooks.json").write_text(old)
    git(root, "add", "-A")
    git(root, "commit", "-qm", "codex")
    proc, out = _upgrade(root)
    assert out["codex_adapter"]["action"] == "refreshed"
    assert (root / ".harness/cache/hooks.json.pre-0.10").read_text() == old
    [line] = [h for h in out["human_checks"] if "hooks.json.pre-0.10" in h]
    assert len(line.split()) <= 25
    assert "./my-own-hook.sh" in (root / ".codex/hooks.json").read_text()


def test_a_backup_is_never_overwritten(tmp_path):
    from engine.upgrade_010 import keep_backup
    first = keep_backup(tmp_path, "AGENTS.md", b"one\n")
    assert first == ".harness/cache/AGENTS.md.pre-0.10"
    assert keep_backup(tmp_path, "AGENTS.md", b"one\n") == first
    second = keep_backup(tmp_path, "AGENTS.md", b"two\n")
    assert second != first
    assert (tmp_path / first).read_bytes() == b"one\n"
    assert (tmp_path / second).read_bytes() == b"two\n"


def test_the_agents_md_backup_survives_a_rerun_and_its_check_says_gitignored(tmp_path):
    from engine.upgrade_w8 import AGENTS_STEP, BACKUP_REL
    root = build_astralabs_094_repo(tmp_path / "repo")
    legacy = (root / "AGENTS.md").read_bytes()
    (root / ".harness/cache").mkdir(parents=True, exist_ok=True)
    (root / BACKUP_REL).write_bytes(b"an older backup\n")
    report = AGENTS_STEP.apply(root, lambda q: True)
    assert (root / BACKUP_REL).read_bytes() == b"an older backup\n"
    [kept] = [p for p in (root / ".harness/cache").glob("AGENTS.md.pre-0.10*")
              if p.read_bytes() == legacy]
    assert any(kept.name in line for line in report)
    advice = AGENTS_STEP.advise(root)
    assert advice and all("gitignored" in a for a in advice)
    assert all(len(a.split()) <= 25 for a in advice)


# ------------------------------------------------------------ 6. last stage
def test_a_failure_while_recording_the_changes_fails_the_upgrade(tmp_path, monkeypatch):
    from engine import upgrade_report as rep
    from engine.cli.upgrade import upgrade_project
    root = build_astralabs_094_repo(tmp_path / "repo")

    def boom(*args):
        raise OSError("disk full")
    monkeypatch.setattr(rep, "save_carry", boom)
    out = upgrade_project(root, yes=True)
    assert out["status"] == "failed"
    assert out["commit"] is None
    [row] = [f for f in out["failures"]
             if f.get("stage") == "record the changes for the next run"]
    assert row["line"].startswith("upgrade STAGE_FAILED")


# ------------------------------------------------------------ 8. JSONL
ROW_BREAK = "a b"


def test_merge_slice_reads_a_closed_row_with_a_line_separator(tmp_path):
    root = build_toy_repo(tmp_path / "toy")
    git(root, "checkout", "-q", "-b", "slice/s-sep")
    row = {"id": "s-sep", "status": "closed", "title": ROW_BREAK}
    with (root / ".harness/backlog.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    git(root, "commit", "-qam", "closed row")
    git(root, "checkout", "-q", "-")
    (root / "telemetry.py").write_text("# dirty\n")
    proc = run_cli("merge-slice", "--slice", "s-sep", root=root)
    out = json.loads(proc.stdout)
    assert "not closed" not in out.get("reason", ""), out
    assert "clean tracked worktree" in out["reason"]


def test_close_recovery_reads_head_rows_with_a_line_separator(tmp_path, monkeypatch):
    from engine.cli import closure_state
    root = build_toy_repo(tmp_path / "toy")
    row = {"id": "s-sep", "status": "closed", "closed_commit": "abc",
           "title": ROW_BREAK}
    with (root / ".harness/backlog.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    git(root, "commit", "-qam", "closed row")
    path = closure_state.journal_path(root, "s-sep")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"result": {"source_commit": "abc"}}))
    finished = []
    monkeypatch.setattr(closure_state, "finish_closure",
                        lambda r, result: finished.append(result) or result)
    closure_state.recover_closure(root, "s-sep")
    assert finished and finished[0]["recovered"] is True


# ------------------------------------------------------------ 9. CRLF
def test_crlf_ignore_and_attribute_files_stay_crlf(tmp_path):
    root = build_astralabs_094_repo(tmp_path / "repo")
    for name in (".gitignore", ".gitattributes"):
        path = root / name
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    git(root, "commit", "-qam", "crlf")
    proc, out = _upgrade(root)
    assert out["status"] == "upgraded", out["failures"]
    for name in (".gitignore", ".gitattributes"):
        assert name in out["files"]["modified"]
        data = (root / name).read_bytes()
        assert data.count(b"\n") == data.count(b"\r\n"), (name, data)


def test_write_lines_keeps_the_files_line_ending(tmp_path):
    from engine.upgrade_010 import write_lines
    path = tmp_path / ".gitignore"
    path.write_bytes(b"a\nb\n")
    write_lines(path, ["a"])
    assert path.read_bytes() == b"a\n"
    path.write_bytes(b"a\r\nb\r\n")
    write_lines(path, ["a", "c"])
    assert path.read_bytes() == b"a\r\nc\r\n"
    write_lines(path, [])
    assert path.read_bytes() == b""


# ------------------------------------------------------------ 11. step ids
@pytest.mark.parametrize("bad", ["agents-md", "x1.thing", "w.thing", "wx.thing"])
def test_a_step_id_without_a_workstream_is_refused(bad):
    from engine import HarnessError, upgrade_010
    before = list(upgrade_010.STEPS)
    with pytest.raises(HarnessError):
        upgrade_010.register(upgrade_010.Step(id=bad, title="t",
                                              describe=lambda r: [],
                                              apply=lambda r, a: []))
    assert upgrade_010.STEPS == before


# ------------------------------------------------------------ 12. minors
def test_the_missing_dependencies_line_is_capped():
    from engine.upgrade_report import human_checks
    deps = ["pkg-a", "pkg-b", "pkg-c", "pkg-d", "pkg-e", "pkg-f"]
    out = human_checks([], pending=[], staged_before=[], dirty_before=[],
                       files={"added": [], "modified": [], "removed": []},
                       checks={"doctor": {"deps_missing": deps}}, is_repo=True)
    [line] = [h for h in out if "dependencies" in h]
    assert "and 3 more" in line
    assert len(line.split()) <= 25
