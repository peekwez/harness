"""C4 acceptance: rebuild from log equals live; provenance walk; concurrent
appends lose no events; git-notes mirror + orphan detection."""
import json
import subprocess
import sys

import pytest

from conftest import git
from engine.graph import (GraphError, append_edge, load_edges, neighbors,
                          orphaned_notes, provenance, read_notes, rebuild,
                          uses_vs_declares, write_note)


def seed_edges(toy):
    append_edge(toy, "declares_dep", "slice:slice-042", "module:telemetry")
    append_edge(toy, "declares_dep", "slice:slice-042", "module:config")
    append_edge(toy, "uses", "slice:slice-042", "module:telemetry")
    append_edge(toy, "uses", "slice:slice-042", "module:util")
    append_edge(toy, "implements", "slice:slice-042", "module:orders")
    append_edge(toy, "remembers", "memory:mem-1", "module:telemetry")
    append_edge(toy, "produced_by", "module:orders", "commit-abc",
                commit="commit-abc")
    append_edge(toy, "governs", "adr:007", "module:telemetry")


def test_rebuild_from_log_equals_live(toy):
    seed_edges(toy)
    live = load_edges(toy)
    g = rebuild(toy)
    assert {e["from"] for e in live} | {e["to"] for e in live} == g["nodes"]
    flat = [e for edges in g["adj"].values() for e in edges]
    assert sorted(flat, key=str) == sorted(live, key=str)


def test_provenance_walk_returns_authored_chain(toy):
    seed_edges(toy)
    p = provenance(toy, "telemetry")
    assert "slice:slice-042" in p["slices"]
    assert "memory:mem-1" in p["memories"]
    assert "adr:007" in p["decisions"]
    p2 = provenance(toy, "orders")
    assert "commit-abc" in p2["commits"]


def test_uses_vs_declares_diff(toy):
    seed_edges(toy)
    ud = uses_vs_declares(toy, "slice-042")
    assert ud["undeclared"] == ["module:util"]
    assert ud["unused"] == ["module:config"]
    assert ud["unresolved"] == ["module:util"]
    append_edge(toy, "override", "slice:slice-042", "module:util",
                meta={"justification": "stdlib-ish helper", "rule_ref": "gate:G5"})
    assert uses_vs_declares(toy, "slice-042")["unresolved"] == []


def test_unknown_edge_type_fails_loud(toy):
    with pytest.raises(GraphError):
        append_edge(toy, "likes", "a", "b")


def test_concurrent_appends_lose_no_events(toy, plugin_root):
    code = (
        "import sys; sys.path.insert(0, sys.argv[1])\n"
        "from engine.graph import append_edge\n"
        "for i in range(200):\n"
        "    append_edge(sys.argv[2], 'touches', f'slice:{sys.argv[3]}', "
        "f'file:f{i}')\n")
    procs = [subprocess.Popen([sys.executable, "-c", code, str(plugin_root),
                               str(toy), f"w{n}"]) for n in (1, 2)]
    for p in procs:
        assert p.wait() == 0
    edges = load_edges(toy)
    assert len(edges) == 400
    for n in (1, 2):
        assert sum(1 for e in edges if e["from"] == f"slice:w{n}") == 200


def test_git_notes_mirror_and_orphan_detection(toy):
    payload = {"slice_id": "slice-042", "modules_touched": ["orders.py"],
               "registry_used": ["telemetry"], "memory_ids": []}
    head = git(toy, "rev-parse", "HEAD").stdout.strip()
    write_note(toy, head, payload)
    notes = read_notes(toy)
    assert any(n["payload"] == payload for n in notes)
    assert orphaned_notes(toy) == []

    # orphan: note a commit, then throw the commit away
    (toy / "tmp.txt").write_text("x")
    git(toy, "add", "tmp.txt")
    git(toy, "commit", "-qm", "throwaway")
    doomed = git(toy, "rev-parse", "HEAD").stdout.strip()
    write_note(toy, doomed, {"slice_id": "doomed"})
    git(toy, "reset", "--hard", "-q", "HEAD~1")
    git(toy, "reflog", "expire", "--expire=now", "--all")
    git(toy, "prune")
    orphans = orphaned_notes(toy)
    assert any(n["commit"] == doomed for n in orphans)
