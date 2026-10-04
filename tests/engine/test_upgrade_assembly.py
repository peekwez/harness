"""harness upgrade: order, dry run, self-hosting, step crashes, final checks."""
from __future__ import annotations

import io
import json
import shutil

from conftest import build_astralabs_094_repo, git, run_cli, tree_bytes
from engine import append_jsonl, read_jsonl


def _up(root, *args):
    proc = run_cli("upgrade", *args, root=root)
    return proc, (json.loads(proc.stdout) if proc.stdout.strip() else {})


def test_plan_runs_legacy_repairs_then_010_steps_then_checks():
    """W8-P1: the 0.8 and 0.9 repairs read old shapes before the 0.10 steps
    rewrite them; the registry refresh reads only 0.10 rows."""
    from engine.cli.upgrade import PROJECT_PLAN
    assert len(PROJECT_PLAN) == 13
    assert PROJECT_PLAN[0] == "migrate substrate schema"
    assert (PROJECT_PLAN.index("canonicalize legacy G5 dependency overrides")
            < PROJECT_PLAN.index("repair legacy graph provenance")
            < PROJECT_PLAN.index("run the 0.10 upgrade steps")
            < PROJECT_PLAN.index("refresh harness-owned Claude settings")
            < PROJECT_PLAN.index("refresh clean registry derivations")
            < PROJECT_PLAN.index("validate substrate schema"))
    assert PROJECT_PLAN[-2:] == ["run doctor and verify", "propose one commit"]
    assert "force-regenerate shadows" not in PROJECT_PLAN


def test_dry_run_lists_every_registered_step_and_writes_nothing(tmp_path):
    from engine import upgrade_010
    root = build_astralabs_094_repo(tmp_path / "astra")
    before, status = tree_bytes(root), git(root, "status", "--porcelain").stdout
    proc, out = _up(root, "--dry-run")
    assert proc.returncode == 0, proc.stderr
    assert out["dry_run"] is True
    assert [r["id"] for r in out["steps"]] == [s.id for s in upgrade_010.STEPS]
    assert all(set(r) == {"id", "title", "destructive", "changes"} for r in out["steps"])
    pending = "\n".join(c for r in out["steps"] for c in r["changes"])
    for needle in (".harness/shadows", "telemetry", ".harness/memory", "config.yaml"):
        assert needle in pending, needle
    assert tree_bytes(root) == before
    assert git(root, "status", "--porcelain").stdout == status


def test_dry_run_previews_the_memory_git_lines_while_the_folder_exists(tmp_path):
    """W8-P12: `describe` stays [] while .harness/memory/ exists, but the
    dry run still shows the lines that the step removes after the retire."""
    from engine import upgrade_010
    root = build_astralabs_094_repo(tmp_path / "astra")
    step = next(s for s in upgrade_010.STEPS if s.id == "w3.memory-git-lines")
    assert step.describe(root) == []
    proc, out = _up(root, "--dry-run")
    row = next(r for r in out["steps"] if r["id"] == "w3.memory-git-lines")
    assert row["changes"], row
    assert all("(after w3.retire-durable-memory)" in c for c in row["changes"])


def test_make_ask_yes_accepts_without_reading():
    from engine.cli.upgrade import make_ask

    class NoRead(io.StringIO):
        def readline(self, *args):
            raise AssertionError("read stdin")
    assert make_ask(True, stdin=NoRead())("Delete .harness/shadows?") is True


def test_make_ask_without_a_tty_declines_without_reading():
    from engine.cli.upgrade import make_ask
    assert make_ask(False, stdin=io.StringIO("y\n"), stderr=io.StringIO())("Delete?") is False


def test_make_ask_on_a_tty_reads_one_answer():
    from engine.cli.upgrade import make_ask

    class Tty(io.StringIO):
        def isatty(self):
            return True
    err = io.StringIO()
    assert make_ask(False, stdin=Tty("y\n"), stderr=err)("Delete .harness/shadows?") is True
    assert "Delete .harness/shadows? [y/N] " in err.getvalue()
    assert make_ask(False, stdin=Tty("\n"), stderr=io.StringIO())("Delete?") is False


def test_make_ask_without_streams_uses_the_tty_ask_seam(monkeypatch):
    """W8-P3: tests monkeypatch `upgrade_010.tty_ask`; the default ask calls it."""
    from engine import upgrade_010
    from engine.cli.upgrade import make_ask
    asked = []
    monkeypatch.setattr(upgrade_010, "tty_ask", lambda q: asked.append(q) or True)
    assert make_ask(False)("Delete?") is True
    assert asked == ["Delete?"]


def test_a_094_repo_upgrades_with_yes_and_proposes_one_commit(tmp_path):
    from engine.cli.upgrade import make_ask, upgrade_project
    root = build_astralabs_094_repo(tmp_path / "astra")
    out = upgrade_project(root, ask=make_ask(True))
    assert out["status"] == "upgraded", out["failures"]
    assert out["failures"] == []
    assert out["checks"]["doctor"]["passed"] and out["checks"]["verify"]["passed"]
    for key in ("steps", "advice", "checks", "human_checks", "files", "commit",
                "warnings", "schema", "registry", "schema_validation"):
        assert key in out, key
    assert out["commit"]["message"] == "harness: upgrade to 0.10"
    assert ".harness/schema_version" in out["commit"]["paths"]
    # W8-P15: W1 already staged the shadow deletion, so `git commit` takes it
    shadow = ".harness/shadows/libs/core/src/astra_core/config.py.json"
    assert shadow in out["files"]["removed"]
    assert shadow not in out["commit"]["paths"]
    assert sorted(out["registry"]["refreshed"]) == ["billing", "config"]
    # upgrade stages only W1's and W3's `git rm --cached`; it never commits
    assert git(root, "rev-list", "--count", "HEAD").stdout.strip() == "1"
    staged = git(root, "diff", "--cached", "--name-only").stdout.split()
    assert staged and all(p.startswith((".harness/shadows/", ".harness/memory/"))
                          for p in staged)
    assert not (root / ".harness/memory").exists()


def test_a_declined_destructive_step_leaves_the_upgrade_incomplete(tmp_path):
    from engine.cli.upgrade import make_ask, upgrade_project
    root = build_astralabs_094_repo(tmp_path / "astra")
    out = upgrade_project(root, ask=make_ask(False, stdin=io.StringIO(),
                                             stderr=io.StringIO()))
    assert out["status"] == "incomplete"
    assert out["commit"] is None
    assert (root / ".harness/shadows").exists()
    skipped = [w for w in out["warnings"] if "skipped: needs confirmation" in w]
    assert any(w.startswith("w1.untrack-shadows:") and "--yes" in w for w in skipped)
    assert any(h.startswith("w1.untrack-shadows:") and "needs confirmation" in h
               for h in out["human_checks"])
    assert any("harness upgrade --yes" in h for h in out["human_checks"])


def test_self_hosted_repo_is_not_vendored(tmp_path, monkeypatch):
    from engine.cli import upgrade
    root = build_astralabs_094_repo(tmp_path / "astra")
    shutil.rmtree(root / ".harness/engine")
    monkeypatch.setattr(upgrade, "PLUGIN_ROOT", root)
    out = upgrade.upgrade_project(root, ask=upgrade.make_ask(True))
    assert out["vendored_engine"]["action"] == "self-hosted"
    assert not (root / ".harness/engine").exists()


def test_step_crash_names_the_step_and_a_rerun_finishes(tmp_path, monkeypatch):
    from engine import upgrade_010
    from engine.cli.upgrade import make_ask, upgrade_project
    root = build_astralabs_094_repo(tmp_path / "astra")
    (root / "boom.flag").write_text("x")

    def describe(r):
        return ["will crash"] if (r / "boom.flag").exists() else []

    def apply(r, ask):
        raise RuntimeError("disk full")
    bomb = upgrade_010.Step(id="w8.test-bomb", title="Crash for the test.",
                            describe=describe, apply=apply)
    real = list(upgrade_010.STEPS)
    monkeypatch.setattr(upgrade_010, "STEPS", [*real, bomb])
    out = upgrade_project(root, ask=make_ask(True))
    assert out["status"] == "failed"
    failure = next(f for f in out["failures"] if f["code"] == "STEP_FAILED")
    assert failure["step"] == "w8.test-bomb"
    assert "disk full" in failure["text"]
    assert "harness upgrade --yes" in failure["fix"]
    assert out["commit"] is None
    assert not (root / ".harness/shadows").exists()      # earlier steps kept their writes
    monkeypatch.setattr(upgrade_010, "STEPS", real)
    (root / "boom.flag").unlink()
    again = upgrade_project(root, ask=make_ask(True))
    assert again["status"] in ("upgraded", "already on 0.10"), again["failures"]


def test_a_preexisting_problem_has_no_owning_step(tmp_path):
    from engine.cli.upgrade import make_ask, upgrade_project
    root = build_astralabs_094_repo(tmp_path / "astra")
    (root / ".worktrees" / "ghost").mkdir(parents=True)
    out = upgrade_project(root, ask=make_ask(True))
    assert out["status"] == "checks failed"
    failure = next(f for f in out["failures"] if f["code"] == "stale_worktrees")
    assert failure["step"] == "none"
    assert failure["fix"].startswith("git worktree remove --force")
    assert out["commit"] is None


def test_final_checks_name_the_step_that_broke_the_substrate(tmp_path, monkeypatch):
    from engine import upgrade_010
    from engine.cli.upgrade import make_ask, upgrade_project
    root = build_astralabs_094_repo(tmp_path / "astra")

    def describe(r):
        rows = read_jsonl(r / ".harness/backlog.jsonl")
        return [] if any(x["id"] == "slice-bad" for x in rows) else [
            "append a row to .harness/backlog.jsonl"]

    def apply(r, ask):
        append_jsonl(r / ".harness/backlog.jsonl", {
            "id": "slice-bad", "status": "nonsense", "declares_dep": [],
            "acceptance": [], "predicted_files": [],
            # w5.legacy-verification ran first; without this it has new work
            "legacy_verification": True})
        return ["appended slice-bad to .harness/backlog.jsonl"]
    breaker = upgrade_010.Step(id="w8.test-breaker", title="Break the backlog for the test.",
                               describe=describe, apply=apply)
    monkeypatch.setattr(upgrade_010, "STEPS", [*upgrade_010.STEPS, breaker])
    out = upgrade_project(root, ask=make_ask(True))
    assert out["status"] == "checks failed"
    owned = [f for f in out["failures"] if f["step"] == "w8.test-breaker"]
    assert owned and all(f["fix"] for f in owned)
    assert all("Step: w8.test-breaker" in f["line"] for f in owned)


def test_a_broken_config_is_a_failure_and_keeps_the_claude_settings(tmp_path):
    from engine.cli.upgrade import make_ask, upgrade_project
    root = build_astralabs_094_repo(tmp_path / "astra")
    settings = (root / ".claude/settings.json").read_bytes()
    (root / ".harness/config.yaml").write_text("gates: [unclosed\n")
    out = upgrade_project(root, ask=make_ask(True))
    assert out["status"] == "failed"
    crash = next(f for f in out["failures"] if f["code"] == "STEP_FAILED")
    assert "config.yaml is not valid YAML" in crash["text"]
    failure = next(f for f in out["failures"] if f["code"] == "CONFIG_INVALID")
    assert "harness upgrade --yes" in failure["fix"]
    assert out["claude"] == {}
    assert (root / ".claude/settings.json").read_bytes() == settings
    assert out["commit"] is None
