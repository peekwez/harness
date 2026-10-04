"""w8.agents-md: refresh only harness-written AGENTS.md files."""
from __future__ import annotations

from conftest import (build_astralabs_094_repo, build_legacy_08_repo)
from engine import upgrade_w8
from engine.cli.common import PLUGIN_ROOT

TEMPLATE = (PLUGIN_ROOT / "templates" / "agents-md.md").read_text()


def test_legacy_file_is_backed_up_then_replaced(tmp_path):
    legacy = upgrade_w8.LEGACY_HEADING + "\nold rules\n"
    (tmp_path / "AGENTS.md").write_text(legacy)
    assert upgrade_w8.agents_md_state(tmp_path) == "legacy"
    assert upgrade_w8.agents_md_describe(tmp_path)
    report = upgrade_w8.agents_md_apply(tmp_path, lambda q: True)
    assert (tmp_path / "AGENTS.md").read_text() == TEMPLATE
    assert (tmp_path / upgrade_w8.BACKUP_REL).read_text() == legacy
    assert any("replaced AGENTS.md" in line for line in report)
    assert all(len(line.split()) <= 25 for line in report)
    assert upgrade_w8.agents_md_describe(tmp_path) == []
    advice = upgrade_w8.agents_md_advise(tmp_path)
    assert advice[0].startswith("check: compare")
    assert "after the skill renames" in advice[0]
    assert all(len(line.split()) <= 25 for line in advice)


def test_declined_legacy_refresh_changes_nothing(tmp_path):
    (tmp_path / "AGENTS.md").write_text(upgrade_w8.LEGACY_HEADING + "\n")
    report = upgrade_w8.agents_md_apply(tmp_path, lambda q: False)
    assert report == [upgrade_w8.SKIPPED]
    assert upgrade_w8.agents_md_state(tmp_path) == "legacy"


def test_custom_file_is_advice_only(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# Team rules\n")
    assert upgrade_w8.agents_md_state(tmp_path) == "custom"
    assert upgrade_w8.agents_md_describe(tmp_path) == []
    assert upgrade_w8.agents_md_advise(tmp_path) == [
        "check: AGENTS.md is not harness-written. Compare it with the "
        "harness template and add the 0.10 rules by hand."]


def test_current_file_is_left_alone_even_when_edited(tmp_path):
    (tmp_path / "AGENTS.md").write_text(TEMPLATE + "\nlocal note\n")
    assert upgrade_w8.agents_md_state(tmp_path) == "current"
    assert upgrade_w8.agents_md_describe(tmp_path) == []
    assert upgrade_w8.agents_md_advise(tmp_path) == []


def test_missing_file_is_never_created(tmp_path):
    assert upgrade_w8.agents_md_state(tmp_path) == "missing"
    assert upgrade_w8.agents_md_describe(tmp_path) == []
    assert upgrade_w8.agents_md_apply(tmp_path, lambda q: True) == []
    assert upgrade_w8.agents_md_advise(tmp_path) == []
    assert not (tmp_path / "AGENTS.md").exists()


def test_step_registers_before_stale_merge_rules():
    from engine import upgrade_010
    ids = [s.id for s in upgrade_010.STEPS]
    assert ids.index("w8.agents-md") < ids.index("w8.stale-merge-rules")
    assert upgrade_w8.AGENTS_STEP.destructive is True


def test_old_files_leave_nothing_pending_for_w4_and_w6(tmp_path):
    """The 0.10 template has the STE-80 rule and explore, so one run settles it."""
    from engine import upgrade_010
    from engine.cli.upgrade import make_ask, upgrade_project
    for n, build in enumerate([build_legacy_08_repo, build_astralabs_094_repo]):
        root = build(tmp_path / f"repo{n}")
        assert (root / "AGENTS.md").read_text().startswith(upgrade_w8.LEGACY_HEADING)
        out = upgrade_project(root, ask=make_ask(True))
        assert "w8.agents-md" in [r["id"] for r in out["steps"]]
        assert (root / "AGENTS.md").read_text() == TEMPLATE
        assert (root / upgrade_w8.BACKUP_REL).exists()
        pending = {s.id: s.describe(root) for s in upgrade_010.STEPS
                   if s.describe(root)}
        assert pending == {}
        assert upgrade_project(root, ask=make_ask(True))["steps"] == []
