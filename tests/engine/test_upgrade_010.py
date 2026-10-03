"""The 0.10 upgrade step framework: plan, run, ask, idempotence, wiring."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from conftest import build_toy_repo, run_cli
from engine import SCHEMA_VERSION, HarnessError
from engine import upgrade_010
from engine.upgrade_010 import SKIPPED, Step


def _marker_step(name="w0.marker", destructive=False, asks=True, leaves=False):
    """A step that writes `<name>.done` in the root."""
    def describe(root: Path) -> list[str]:
        return [] if (root / f"{name}.done").exists() else [f"write {name}.done"]

    def apply(root: Path, ask) -> list[str]:
        if destructive and asks and not ask(f"Write {name}.done?"):
            return [SKIPPED]
        if not leaves:
            (root / f"{name}.done").write_text("ok\n")
        return [f"wrote {name}.done"]

    return Step(id=name, title=f"Write {name}.done.", describe=describe,
                apply=apply, destructive=destructive)


@pytest.fixture
def steps(monkeypatch):
    registered: list[Step] = []
    monkeypatch.setattr(upgrade_010, "STEPS", registered)
    return registered



def test_advice_is_reported_but_never_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(upgrade_010, "STEPS", [])
    step = Step(id="w0.advice", title="Advise only.", describe=lambda r: [],
                apply=lambda r, a: [], advise=lambda r: ["check: add the import"])
    upgrade_010.register(step)
    assert upgrade_010.plan(tmp_path) == []
    assert upgrade_010.run(tmp_path, upgrade_010.always_yes, dry_run=False) == []
    assert upgrade_010.advice(tmp_path) == [
        {"id": "w0.advice", "check": "check: add the import"}]

def test_schema_version_is_two_and_migration_one_only_stamps(tmp_path):
    from engine.migrate import MIGRATIONS, migrate
    root = build_toy_repo(tmp_path / "toy")
    (root / ".harness" / "schema_version").write_text("1\n")
    before = {p: p.read_bytes() for p in (root / ".harness").glob("*.jsonl")}
    assert SCHEMA_VERSION == 2 and 1 in MIGRATIONS
    assert migrate(root)["applied"] == [2]
    assert (root / ".harness" / "schema_version").read_text() == "2\n"
    assert {p: p.read_bytes() for p in before} == before


def test_register_rejects_a_duplicate_id(steps):
    upgrade_010.register(_marker_step())
    with pytest.raises(HarnessError, match="w0.marker"):
        upgrade_010.register(_marker_step())


def test_plan_lists_only_steps_with_pending_changes(steps, tmp_path):
    upgrade_010.register(_marker_step("w0.a"))
    upgrade_010.register(_marker_step("w0.b"))
    (tmp_path / "w0.b.done").write_text("ok\n")
    assert upgrade_010.plan(tmp_path) == [
        {"id": "w0.a", "title": "Write w0.a.done.", "changes": ["write w0.a.done"]}]


def test_dry_run_changes_nothing(steps, tmp_path):
    upgrade_010.register(_marker_step())
    out = upgrade_010.run(tmp_path, upgrade_010.always_yes, dry_run=True)
    assert [row["id"] for row in out] == ["w0.marker"]
    assert "report" not in out[0]
    assert not (tmp_path / "w0.marker.done").exists()


def test_run_applies_and_a_second_run_does_nothing(steps, tmp_path):
    upgrade_010.register(_marker_step())
    first = upgrade_010.run(tmp_path, upgrade_010.always_yes, dry_run=False)
    assert first[0]["report"] == ["wrote w0.marker.done"]
    assert upgrade_010.run(tmp_path, upgrade_010.always_yes, dry_run=False) == []


def test_a_step_that_leaves_changes_fails_and_names_the_step(steps, tmp_path):
    upgrade_010.register(_marker_step(leaves=True))
    with pytest.raises(HarnessError, match="w0.marker"):
        upgrade_010.run(tmp_path, upgrade_010.always_yes, dry_run=False)


def test_destructive_step_must_ask_first(steps, tmp_path):
    upgrade_010.register(_marker_step(destructive=True, asks=False))
    with pytest.raises(HarnessError, match="without asking"):
        upgrade_010.run(tmp_path, upgrade_010.always_yes, dry_run=False)


def test_declined_destructive_step_is_skipped_not_failed(steps, tmp_path):
    upgrade_010.register(_marker_step(destructive=True))
    out = upgrade_010.run(tmp_path, lambda question: False, dry_run=False)
    assert out[0]["report"] == [SKIPPED]
    assert not (tmp_path / "w0.marker.done").exists()


def test_tty_ask_answers_no_without_a_terminal(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    assert upgrade_010.tty_ask("Delete it?") is False


def test_upgrade_runs_steps_after_the_schema_migration(steps, tmp_path):
    from engine.cli.upgrade import upgrade_project
    seen = []

    def describe(root):
        return [] if seen else ["record the schema version"]

    def apply(root, ask):
        seen.append((root / ".harness" / "schema_version").read_text().strip())
        return ["recorded"]

    upgrade_010.register(Step("w0.order", "Record the schema version.",
                              describe, apply))
    root = build_toy_repo(tmp_path / "toy")
    (root / ".harness" / "schema_version").write_text("1\n")
    report = upgrade_project(root, yes=True)
    assert seen == ["2"]
    assert report["steps"][0]["id"] == "w0.order"


def test_dry_run_reports_steps_and_writes_nothing(steps, tmp_path):
    from engine.cli.upgrade import upgrade_project
    upgrade_010.register(_marker_step())
    root = build_toy_repo(tmp_path / "toy")
    report = upgrade_project(root, dry_run=True)
    assert report["steps"] == [{"id": "w0.marker", "title": "Write w0.marker.done.",
                                "changes": ["write w0.marker.done"]}]
    assert not (root / "w0.marker.done").exists()


def test_skipped_step_is_named_in_the_warnings(steps, tmp_path, monkeypatch):
    from engine.cli.upgrade import upgrade_project
    upgrade_010.register(_marker_step(destructive=True))
    monkeypatch.setattr(upgrade_010, "tty_ask", lambda question: False)
    root = build_toy_repo(tmp_path / "toy")
    report = upgrade_project(root)
    assert any("w0.marker" in w and "--yes" in w for w in report["warnings"])


def test_cli_accepts_yes(tmp_path):
    root = build_toy_repo(tmp_path / "toy")
    proc = run_cli("upgrade", "--yes", root=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "steps" in json.loads(proc.stdout)
