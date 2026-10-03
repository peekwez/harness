"""`harness memory promote|changed` (D-0.10-02)."""
import json
import os
import re

from conftest import git, run_cli
from engine import get_slice, save_slice


def test_memory_promote_text_via_cli(toy):
    proc = run_cli("memory", "promote", "--text", "Deploys happen on Tuesdays.",
                   root=toy)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["promoted"] is True
    assert out["path"] == ".claude/memory/shared/deploys-happen-on-tuesdays.md"
    assert (toy / out["path"]).exists()


def test_memory_promote_file_via_cli_with_name(toy, tmp_path):
    fact = tmp_path / "x.md"
    fact.write_text("Use uv for every Python command.\n")
    proc = run_cli("memory", "promote", str(fact), "--name", "Python tooling",
                   root=toy)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["path"].endswith("/python-tooling.md")


def test_memory_promote_needs_exactly_one_fact(toy, tmp_path):
    assert run_cli("memory", "promote", root=toy).returncode == 2
    fact = tmp_path / "a.md"
    fact.write_text("x")
    proc = run_cli("memory", "promote", str(fact), "--text", "y", root=toy)
    assert proc.returncode == 2
    assert "one fact" in proc.stderr


def test_memory_promote_engine_error_exits_one(toy, tmp_path):
    proc = run_cli("memory", "promote", str(tmp_path / "nope.md"), root=toy)
    assert proc.returncode == 1
    assert "not found" in json.loads(proc.stderr)["error"]


def test_removed_memory_subcommands_are_gone(toy):
    for sub in ("write", "flush", "compact"):
        proc = run_cli("memory", sub, root=toy)
        assert proc.returncode == 2
        assert "invalid choice" in proc.stderr


def _personal_dir(home, toy):
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(toy.resolve()))
    return home / ".claude" / "projects" / slug / "memory"


def test_memory_changed_lists_files_since_slice_start(toy, tmp_path):
    head = git(toy, "rev-parse", "HEAD").stdout.strip()
    started = int(git(toy, "show", "-s", "--format=%ct", head).stdout.strip())
    row = get_slice(toy, "slice-042")
    row["started_at_commit"] = head
    save_slice(toy, row)
    home = tmp_path / "home"
    env = {"HOME": str(home), "CLAUDE_CONFIG_DIR": ""}
    mem = _personal_dir(home, toy)
    mem.mkdir(parents=True)
    for name, mtime in (("old.md", started - 100), ("new.md", started + 100)):
        (mem / name).write_text(name)
        os.utime(mem / name, (mtime, mtime))

    proc = run_cli("memory", "changed", "--slice", "slice-042", root=toy, env=env)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["dir"] == str(mem)
    assert out["files"] == [str(mem / "new.md")]

    proc = run_cli("memory", "changed", "--since", "1970-01-01T00:00:00Z",
                   root=toy, env=env)
    assert sorted(json.loads(proc.stdout)["files"]) == sorted(
        [str(mem / "new.md"), str(mem / "old.md")])


def test_memory_changed_needs_a_start(toy, tmp_path):
    env = {"HOME": str(tmp_path / "home")}
    proc = run_cli("memory", "changed", root=toy, env=env)
    assert proc.returncode == 2
    assert "Fix:" in proc.stderr
    proc = run_cli("memory", "changed", "--slice", "slice-042", root=toy, env=env)
    assert proc.returncode == 1
    assert "--since" in json.loads(proc.stderr)["error"]


def test_memory_changed_rejects_a_bad_since(toy, tmp_path):
    env = {"HOME": str(tmp_path / "home")}
    proc = run_cli("memory", "changed", "--since", "garbage", root=toy, env=env)
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr
    assert "Fix:" in proc.stderr
