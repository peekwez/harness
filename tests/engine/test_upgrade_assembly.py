"""harness upgrade: order, dry run, self-hosting, step crashes, final checks."""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys

from conftest import HARNESS_BIN, build_astralabs_094_repo, build_toy_repo, git, run_cli, tree_bytes
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
    assert crash["step"] == out["steps"][-1]["id"]
    failure = next(f for f in out["failures"] if f["code"] == "CONFIG_INVALID")
    assert "harness upgrade --yes" in failure["fix"]
    assert out["claude"] == {}
    assert (root / ".claude/settings.json").read_bytes() == settings
    assert out["commit"] is None


def _noask():
    from engine.cli.upgrade import make_ask
    return make_ask(False, stdin=io.StringIO(), stderr=io.StringIO())


def test_a_second_run_is_already_on_010(tmp_path):
    from engine.cli.upgrade import make_ask, upgrade_project
    root = build_astralabs_094_repo(tmp_path / "astra")
    assert upgrade_project(root, ask=make_ask(True))["status"] == "upgraded"
    two = upgrade_project(root, ask=make_ask(True))
    assert two["status"] == "already on 0.10", (two["files"], two["failures"])
    assert two["commit"] is None


def test_a_crash_after_a_declined_step_names_the_crashing_step(tmp_path, monkeypatch):
    """Fix round 1: the rows before the crash and the skip lines stay."""
    from engine import upgrade_010
    from engine.cli.upgrade import upgrade_project

    def apply(r, ask):
        raise RuntimeError("disk full")
    bomb = upgrade_010.Step(id="w8.bomb", title="b", describe=lambda r: ["x"], apply=apply)
    monkeypatch.setattr(upgrade_010, "STEPS", [*upgrade_010.STEPS, bomb])
    root = build_astralabs_094_repo(tmp_path / "astra")
    out = upgrade_project(root, ask=_noask())
    assert out["status"] == "failed" and out["commit"] is None
    [failure] = [f for f in out["failures"] if f["code"] == "STEP_FAILED"]
    assert failure["step"] == "w8.bomb" and failure["text"] == "RuntimeError: disk full"
    rows = {r["id"]: r for r in out["steps"]}
    assert rows["w1.untrack-shadows"]["report"] == ["skipped: needs confirmation"]
    assert out["steps"][-1]["id"] == "w8.bomb"
    assert any(w.startswith("w1.untrack-shadows:") for w in out["warnings"])
    assert any(h.startswith("w1.untrack-shadows:") for h in out["human_checks"])
    assert out["registry"]["refreshed"] == []        # 0.9 rows may remain


def test_a_stage_that_raises_still_returns_a_report(tmp_path, monkeypatch):
    from engine.cli import upgrade

    def boom(r):
        raise OSError("read-only file system")
    monkeypatch.setattr(upgrade, "_write_workflow", boom)
    root = build_astralabs_094_repo(tmp_path / "astra")
    out = upgrade.upgrade_project(root, ask=upgrade.make_ask(True))
    assert out["status"] == "failed" and out["commit"] is None
    [failure] = [f for f in out["failures"] if f["code"] == "STAGE_FAILED"]
    assert failure["stage"] == "refresh workflow"
    assert failure["detail"] == "read-only file system"
    assert failure["line"].endswith("harness upgrade --yes")
    assert out["registry"]["refreshed"] == []
    assert out["checks"]["doctor"]["passed"] is not None


def test_a_settings_write_error_is_a_stage_failure_not_a_config_one(tmp_path, monkeypatch):
    from engine.cli import upgrade

    def boom(root, config):
        raise OSError("disk full")
    monkeypatch.setattr(upgrade, "_refresh_claude_settings", boom)
    root = build_astralabs_094_repo(tmp_path / "astra")
    out = upgrade.upgrade_project(root, ask=upgrade.make_ask(True))
    codes = {f["code"] for f in out["failures"]}
    assert "STAGE_FAILED" in codes and "CONFIG_INVALID" not in codes
    assert out["status"] == "failed"


def test_a_raising_describe_leaves_the_upgrade_incomplete_not_crashed(tmp_path, monkeypatch):
    from engine import upgrade_010
    from engine.cli.upgrade import make_ask, upgrade_project
    calls = []

    def describe(r):
        calls.append(1)
        if len(calls) > 1:              # fine during the run, broken afterwards
            raise ValueError("cannot read")
        return []
    odd = upgrade_010.Step(id="w8.odd", title="o", describe=describe,
                           apply=lambda r, a: [])
    monkeypatch.setattr(upgrade_010, "STEPS", [*upgrade_010.STEPS, odd])
    root = build_astralabs_094_repo(tmp_path / "astra")
    out = upgrade_project(root, ask=make_ask(True))
    assert out["status"] == "incomplete"
    assert any("w8.odd" in h for h in out["human_checks"])


def test_upgrade_help_offers_yes():
    assert "--yes" in run_cli("upgrade", "--help").stdout


def test_non_tty_without_yes_skips_destructive_steps_and_never_waits(tmp_path):
    from engine import upgrade_010
    root = build_astralabs_094_repo(tmp_path / "astra")
    pending = {s.id for s in upgrade_010.STEPS if s.destructive and s.describe(root)}
    assert pending
    proc = subprocess.run([sys.executable, str(HARNESS_BIN), "--root", str(root), "upgrade"],
                          input="", capture_output=True, text=True, timeout=300)
    out = json.loads(proc.stdout)
    assert proc.returncode == 1
    assert out["status"] == "incomplete"
    lines = {r["id"]: "\n".join(r.get("report", r.get("changes", []))) for r in out["steps"]}
    for step_id in pending:
        assert "needs confirmation" in lines[step_id], (step_id, lines.get(step_id))
    assert any("harness upgrade --yes" in line for line in out["human_checks"])
    assert (root / ".harness/shadows").is_dir()
    assert (root / ".harness/telemetry.jsonl").exists()
    assert (root / ".harness/memory/durable.jsonl").exists()
    assert out["commit"] is None


def test_yes_finishes_and_exits_zero(tmp_path):
    root = build_astralabs_094_repo(tmp_path / "astra")
    proc, out = _up(root, "--yes")
    assert proc.returncode == 0, json.dumps(out.get("failures"), indent=1)
    assert out["status"] == "upgraded"


def test_every_status_maps_to_its_exit_code():
    from types import SimpleNamespace
    from engine.cli import upgrade
    expect = {"upgraded": 0, "already on 0.10": 0, "incomplete": 1,
              "checks failed": 1, "failed": 1}
    for status, code in expect.items():
        orig = upgrade.upgrade_project
        upgrade.upgrade_project = lambda *a, _s=status, **k: {"status": _s}
        try:
            args = SimpleNamespace(root=".", plugin=False, host=None, plugin_id=None,
                                   scope=None, yes=True, dry_run=False)
            assert upgrade.cmd_upgrade(args) == code, status
        finally:
            upgrade.upgrade_project = orig


def test_plugin_upgrade_forwards_yes_and_keeps_an_incomplete_report(tmp_path, monkeypatch):
    from engine.cli import upgrade
    from test_hardening_upgrade import _completed, _plugin_tree
    project = build_toy_repo(tmp_path / "project")
    new_path = _plugin_tree(tmp_path, "new")
    listing = [{"id": "harness@team", "version": "0.10.0", "scope": "user",
                "installPath": str(new_path)}]
    calls = []

    def run(command):
        calls.append(command)
        if command == ["claude", "plugin", "list", "--json"]:
            return _completed(json.dumps(listing))
        if command[:3] == ["claude", "plugin", "update"]:
            return _completed()
        return _completed(json.dumps({"engine_version": "0.10.0", "status": "incomplete"}),
                          returncode=1)
    monkeypatch.setattr(upgrade, "_run_command", run)
    monkeypatch.setattr(upgrade, "_run_host_command", run)
    report = upgrade.upgrade_installed_plugin(project, "claude", yes=True)
    assert calls[-1][-2:] == ["upgrade", "--yes"]
    assert report["project"]["status"] == "incomplete"


def test_long_step_error_line_stays_within_25_words_with_the_fix_last():
    from engine import upgrade_report as rep
    long = "disk full " + " ".join(f"w{i}" for i in range(60))
    rows = [{"id": "w2.b", "error": f"OSError: {long}"}]
    [f] = rep.attribute(rep.reported_step_errors(rows), rows)
    assert len(f["line"].split()) <= 25, f["line"]
    assert "disk full" in f["line"]
    assert f["line"].endswith("Fix: " + rep.STEP_FIX)
