"""Regression tests for immutable closure provenance."""

import shutil

import pytest

from conftest import run_cli
from engine import get_slice, read_jsonl, save_slice, write_jsonl
from engine.graph import (append_edge, load_edges, provenance_gaps,
                          record_dependency_snapshot, record_slice_provenance,
                          slice_provenance_requirements, uses_vs_declares)


COMMIT = "a" * 40


def _closed_slice(toy, evidence):
    sl = get_slice(toy, "slice-042")
    sl.update({"status": "closed", "provenance_version": 1,
               "closed_commit": COMMIT, "closed_files": ["telemetry.py"],
               "closed_evidence": evidence})
    save_slice(toy, sl)
    record_dependency_snapshot(toy, sl["id"], [], sl["closed_files"], commit=COMMIT)
    append_edge(toy, "touches", "slice:slice-042", "file:telemetry.py", commit=COMMIT)
    return sl


@pytest.mark.parametrize("missing", ["produced_by", "shadows", "governs", "satisfies"])
def test_provenance_gaps_rejects_missing_promised_edges(toy, missing):
    evidence = [
        ["touches", "slice:slice-042", "file:telemetry.py"],
        ["produced_by", "module:telemetry", "$closed_commit"],
        ["shadows", "module:telemetry", "file:.harness/shadows/telemetry.py.json"],
        ["governs", "decision:D-041", "module:telemetry"],
        ["satisfies", "slice:slice-042", "file:tests/slices/042_orders.py"],
    ]
    sl = _closed_slice(toy, evidence)
    for kind, source, target in evidence:
        if kind != missing and kind != "touches":
            append_edge(toy, kind, source,
                        COMMIT if target == "$closed_commit" else target,
                        commit=COMMIT)

    assert any(missing in gap for gap in provenance_gaps(toy, sl))


def test_modern_provenance_requires_recorded_closure_evidence(toy):
    sl = _closed_slice(toy, None)
    assert "closed evidence" in " ".join(provenance_gaps(toy, sl)).lower()


def test_requirements_are_the_complete_records_written_at_closure(toy):
    # A manifest match must bind the file even when it is not the primary source.
    registry_path = toy / ".harness" / "registry.jsonl"
    rows = read_jsonl(registry_path)
    rows[0]["source"] = "src/telemetry.py"
    write_jsonl(registry_path, rows)
    expected = {
        ("touches", "slice:slice-042", "file:telemetry.py"),
        ("touches", "slice:slice-042", "module:telemetry"),
        ("produced_by", "module:telemetry", "$closed_commit"),
        ("shadows", "module:telemetry", "file:.harness/shadows/telemetry.py.json"),
        ("governs", "decision:D-041", "module:telemetry"),
        ("satisfies", "slice:slice-042", "file:tests/slices/042_orders.py"),
    }

    requirements = slice_provenance_requirements(toy, "slice-042", ["telemetry.py"])
    assert {tuple(item) for item in requirements} == expected
    record_slice_provenance(toy, "slice-042", COMMIT, ["telemetry.py"])
    written = {(e["type"], e["from"], e["to"])
               for e in load_edges(toy) if e.get("commit") == COMMIT}
    resolved = {(kind, source, COMMIT if target == "$closed_commit" else target)
                for kind, source, target in requirements}
    assert written == resolved


def test_closed_slice_ignores_uncommitted_dependency_snapshot(toy):
    sl = get_slice(toy, "slice-042")
    record_dependency_snapshot(toy, sl["id"], ["module:telemetry"],
                               ["telemetry.py"], commit=COMMIT)
    sl.update({"status": "closed", "provenance_version": 1,
               "closed_commit": COMMIT, "closed_files": ["telemetry.py"]})
    save_slice(toy, sl)

    before = load_edges(toy)
    record_dependency_snapshot(toy, sl["id"], ["module:config"],
                               ["config.py"], commit=None)

    assert load_edges(toy) == before
    assert uses_vs_declares(toy, sl["id"])["uses"] == ["module:telemetry"]


def test_gitless_closure_does_not_promise_a_revision_edge(toy):
    shutil.rmtree(toy / ".git")
    requirements = slice_provenance_requirements(toy, "slice-042", ["telemetry.py"])
    assert "produced_by" not in {item[0] for item in requirements}
    record_dependency_snapshot(toy, "slice-042", [], ["telemetry.py"], commit=None)
    record_slice_provenance(toy, "slice-042", None, ["telemetry.py"])
    sl = get_slice(toy, "slice-042")
    sl.update({"status": "closed", "provenance_version": 1,
               "closed_commit": None, "closed_files": ["telemetry.py"],
               "closed_evidence": requirements})
    save_slice(toy, sl)
    assert provenance_gaps(toy, sl) == []
    assert "INCOMPLETE_GRAPH_PROVENANCE" not in run_cli("verify", root=toy).stdout
