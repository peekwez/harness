"""W8 legacy fixtures look like real 0.8.0 and 0.9.4 substrates."""
from __future__ import annotations

import subprocess
import sys

import pytest

from conftest import (build_astralabs_094_repo, build_legacy_08_repo, git,
                      tree_bytes)
from engine import read_jsonl


@pytest.mark.parametrize("build", [build_legacy_08_repo, build_astralabs_094_repo])
def test_legacy_fixture_is_a_schema_1_substrate_with_committed_shadows(tmp_path, build):
    root = build(tmp_path / "repo")
    assert (root / ".harness/schema_version").read_text() == "1\n"
    assert git(root, "ls-files", ".harness/shadows").stdout.strip()
    assert git(root, "status", "--porcelain").stdout == ""
    assert (root / ".harness/telemetry.jsonl").stat().st_size > 0
    assert (root / ".harness/memory/durable.jsonl").stat().st_size > 0
    assert (root / "contracts/api.yaml").exists()
    statuses = {r["status"] for r in read_jsonl(root / ".harness/backlog.jsonl")}
    assert {"closed", "in_progress"} <= statuses
    assert all("shadow" in r for r in read_jsonl(root / ".harness/registry.jsonl"))
    assert git(root, "notes", "--ref=refs/notes/harness", "list").stdout.strip()
    assert ".git/HEAD" not in tree_bytes(root)


def test_astralabs_fixture_has_the_field_layout(tmp_path):
    root = build_astralabs_094_repo(tmp_path / "astra")
    tracked = set(git(root, "ls-files").stdout.split())
    assert "site/index.html" not in tracked
    assert (root / "site/assets/javascripts/bundle.js.map").exists()
    assert ".harness/shadows/site/assets/javascripts/bundle.js.json" in tracked
    assert ".harness/shadows/tests/unit/test_config.py.json" in tracked
    assert "assets/demo.mp4" in tracked
    assert (root / ".harness/telemetry.archive.jsonl").exists()
    assert all(not b.get("cites") for b in read_jsonl(root / ".harness/boundaries.jsonl"))
    rules = {e["meta"].get("rule_ref") for e in read_jsonl(root / ".harness/edges.jsonl")
             if e["type"] == "override"}
    assert {"gate:G2", "gate:G3", "gate:G7"} <= rules
    assert "/harness:status" in (root / "AGENTS.md").read_text()
    assert (root / ".harness/engine/VERSION").read_text() == "0.9.4\n"


def test_unmarked_astralabs_fixture_has_hand_written_agent_files(tmp_path):
    root = build_astralabs_094_repo(tmp_path / "astra", marked=False)
    assert "harness-enforced" not in (root / "AGENTS.md").read_text()
    assert "harness-enforced" not in (root / "CLAUDE.md").read_text()


def test_the_08_fixture_predates_vendoring_and_canonical_g5_overrides(tmp_path):
    root = build_legacy_08_repo(tmp_path / "old")
    assert not (root / ".harness/engine").exists()
    assert any(e["to"] == "deps:config" for e in read_jsonl(root / ".harness/edges.jsonl"))
    assert "EDIT ME" in (root / ".harness/decisions.jsonl").read_text()


@pytest.mark.parametrize("build,tests", [
    (build_legacy_08_repo, ["tests/slices/040_telemetry.py", "tests/slices/042_orders.py"]),
    (build_astralabs_094_repo, ["tests/slices/041_invoice.py", "tests/slices/043_orders.py",
                                "tests/unit/test_config.py"]),
])
def test_legacy_acceptance_suites_are_green(tmp_path, build, tests):
    root = build(tmp_path / "repo")
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests],
                          cwd=root, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
