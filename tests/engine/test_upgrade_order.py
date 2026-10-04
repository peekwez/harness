"""0.10 steps run in workstream order, and no step undoes another."""
from __future__ import annotations

import re

import pytest

from conftest import (LEGACY_GITATTRIBUTES, LEGACY_GITIGNORE,
                      build_astralabs_094_repo, build_legacy_08_repo)


def test_steps_run_in_workstream_order_with_unique_ids():
    from engine import upgrade_010
    ids = [s.id for s in upgrade_010.STEPS]
    assert len(ids) == len(set(ids)), ids
    waves = [int(re.fullmatch(r"w([1-8])\.[a-z0-9-]+", i).group(1)) for i in ids]
    assert waves == sorted(waves), ids
    assert ids[-1] == "w8.stale-merge-rules"
    assert ids[-2] == "w8.agents-md"


def test_step_titles_are_ste80(tmp_path):
    from engine import upgrade_010
    from engine.lint_text import lint_paths
    titles = tmp_path / "titles.md"
    titles.write_text("".join(f"- {s.title}\n" for s in upgrade_010.STEPS))
    assert lint_paths([titles], None) == []
    assert all(len(s.title.split()) <= 25 for s in upgrade_010.STEPS)


@pytest.mark.parametrize("build", [build_legacy_08_repo, build_astralabs_094_repo])
def test_no_step_undoes_another(tmp_path, build):
    from engine import upgrade_010
    from engine.cli.upgrade import make_ask, upgrade_project
    root = build(tmp_path / "repo")
    out = upgrade_project(root, ask=make_ask(True))
    ran = [r["id"] for r in out["steps"]]
    order = [s.id for s in upgrade_010.STEPS]
    assert ran == [i for i in order if i in ran]
    leftovers = {s.id: s.describe(root) for s in upgrade_010.STEPS if s.describe(root)}
    assert leftovers == {}
    again = upgrade_project(root, ask=make_ask(True))
    assert again["steps"] == []


def test_the_known_writers_of_shared_files_run_in_order():
    """Pins the steps known to write AGENTS.md, .gitattributes and .gitignore
    in the order each reads the one before. This list is kept by hand: a new
    step that writes one of these files must be added here."""
    from engine import upgrade_010
    shared = {
        "AGENTS.md": ["w2.skill-names", "w4.agents-md-ste80",
                      "w6.agents-md-explore", "w8.agents-md"],
        ".gitattributes": ["w1.untrack-shadows", "w2.slice-metrics",
                           "w3.memory-git-lines", "w8.stale-merge-rules"],
        ".gitignore": ["w1.gitignore-cache", "w3.memory-git-lines",
                       "w8.stale-merge-rules"],
    }
    order = [s.id for s in upgrade_010.STEPS]
    for name, writers in shared.items():
        assert all(w in order for w in writers), (name, writers)
        assert writers == [i for i in order if i in writers], name


def test_stale_merge_rules_step_removes_rules_for_removed_files(tmp_path):
    from engine.upgrade_w8 import STEP
    root = tmp_path / "r"
    root.mkdir()
    (root / ".gitattributes").write_text(LEGACY_GITATTRIBUTES)
    (root / ".gitignore").write_text(LEGACY_GITIGNORE)
    changes = STEP.describe(root)
    assert ".gitattributes: remove `.harness/shadows/** merge=ours`" in changes
    assert ".gitignore: remove `.harness/memory/session/`" in changes
    report = STEP.apply(root, lambda question: False)
    assert report and STEP.describe(root) == []
    attrs = (root / ".gitattributes").read_text()
    assert ".harness/shadows" not in attrs
    assert ".harness/telemetry.jsonl" not in attrs
    assert ".harness/memory/durable.jsonl" not in attrs
    assert ".harness/edges.jsonl merge=union" in attrs
    assert ".harness/memory/session/" not in (root / ".gitignore").read_text()


def test_stale_merge_rules_keep_lines_the_engine_still_writes(tmp_path, monkeypatch):
    from engine.cli import common
    from engine.upgrade_w8 import STEP
    monkeypatch.setattr(common, "SUBSTRATE_UNION_MERGE", (".harness/telemetry.jsonl",),
                        raising=False)
    root = tmp_path / "r"
    root.mkdir()
    (root / ".gitattributes").write_text(".harness/telemetry.jsonl merge=union\n")
    assert STEP.describe(root) == []


def test_memory_session_ignore_stays_while_the_memory_folder_exists(tmp_path):
    from engine.upgrade_w8 import STEP
    root = tmp_path / "r"
    (root / ".harness/memory").mkdir(parents=True)
    (root / ".gitignore").write_text(LEGACY_GITIGNORE)
    assert not any(c.startswith(".gitignore") for c in STEP.describe(root))


def test_rules_stay_while_their_subject_exists(tmp_path):
    """A declined untrack or retire keeps the file, so it keeps its rule."""
    from engine.upgrade_w8 import STEP
    root = tmp_path / "r"
    (root / ".harness/shadows").mkdir(parents=True)
    (root / ".harness/memory").mkdir()
    (root / ".harness/telemetry.jsonl").write_text("")
    (root / ".gitattributes").write_text(LEGACY_GITATTRIBUTES)
    (root / ".gitignore").write_text(LEGACY_GITIGNORE)
    assert STEP.describe(root) == []
    assert STEP.apply(root, lambda q: False) == []
    assert (root / ".gitattributes").read_text() == LEGACY_GITATTRIBUTES
    (root / ".harness/telemetry.jsonl").unlink()
    assert STEP.describe(root) == [
        ".gitattributes: remove `.harness/telemetry.jsonl merge=union`"]
