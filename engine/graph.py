"""C4 — Graph store: append-only edges.jsonl + git-notes mirror.

Edges are never updated; a newer event supersedes. The graph is rebuildable
from the log alone. Node IDs are stable logical IDs; commits are the only
nodes whose ID is their hash.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import HarnessError, append_jsonl, harness_dir, now_iso, read_jsonl

EDGE_TYPES = {"implements", "declares_dep", "uses", "shadows", "supersedes",
              "governs", "decided_by", "satisfies", "produced_by", "touches",
              "reviewed_by",
              "remembers", "override"}

NOTES_REF = "refs/notes/harness"


class GraphError(HarnessError):
    pass


def edges_path(root) -> Path:
    return harness_dir(root) / "edges.jsonl"


def append_edge(root, etype, frm, to, commit=None, meta=None) -> dict:
    if etype not in EDGE_TYPES:
        raise GraphError(f"unknown edge type {etype!r}; expected one of {sorted(EDGE_TYPES)}")
    edge = {"ts": now_iso(), "type": etype, "from": frm, "to": to,
            "commit": commit, "meta": meta or {}}
    append_jsonl(edges_path(root), edge)
    return edge


def load_edges(root) -> list:
    return read_jsonl(edges_path(root))


def rebuild(root) -> dict:
    """Adjacency built purely from the append-only log."""
    nodes, adj = set(), {}
    for e in load_edges(root):
        nodes.add(e["from"]); nodes.add(e["to"])
        adj.setdefault(e["from"], []).append(e)
    return {"nodes": nodes, "adj": adj}


def neighbors(root, node) -> list:
    out = []
    for e in load_edges(root):
        if e["from"] == node or e["to"] == node:
            out.append(e)
    return out


def provenance(root, module_id: str) -> dict:
    """Provenance walk: module -> commits -> slices -> memories.
    'Show every decision that shaped this file.'"""
    edges = load_edges(root)
    module = f"module:{module_id}"
    commits = sorted({e["commit"] for e in edges
                      if e.get("commit") and module in (e["from"], e["to"])} |
                     {e["to"] for e in edges
                      if e["from"] == module and e["type"] == "produced_by"})
    slices = sorted({e["from"] for e in edges
                     if e["to"] == module and e["type"] in ("implements", "touches")} |
                    {e["from"] for e in edges
                     if e["type"] == "declares_dep" and e["to"] == module})
    memories = sorted({e["from"] for e in edges
                       if e["to"] == module and e["type"] == "remembers"})
    decisions = sorted({e["to"] for e in edges
                        if e["from"] == module and e["type"] == "decided_by"} |
                       {e["from"] for e in edges
                        if e["to"] == module and e["type"] == "governs"})
    return {"module": module, "commits": commits, "slices": slices,
            "memories": memories, "decisions": decisions}


def _bare(node_id: str) -> str:
    return node_id.split(":", 1)[-1]


def uses_vs_declares(root, slice_id: str) -> dict:
    edges = load_edges(root)
    s = f"slice:{slice_id}"
    uses = {e["to"] for e in edges if e["from"] == s and e["type"] == "uses"}
    declares = {e["to"] for e in edges if e["from"] == s and e["type"] == "declares_dep"}
    overridden = {_bare(e["to"]) for e in edges
                  if e["from"] == s and e["type"] == "override"}
    undeclared = sorted(uses - declares)
    return {"uses": sorted(uses), "declares": sorted(declares),
            "undeclared": undeclared,
            "unused": sorted(declares - uses),
            "overridden": sorted(overridden),
            "unresolved": [u for u in undeclared if _bare(u) not in overridden]}


# ------------------------------------------------------------------ git notes
def _git(root, *args, check=True) -> str:
    proc = subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise GraphError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def write_note(root, commit, payload: dict) -> None:
    """Mirror {slice_id, modules_touched, registry_used, memory_ids} onto the
    commit so provenance travels with the repo."""
    _git(root, "notes", f"--ref={NOTES_REF}", "add", "-f", "-m",
         json.dumps(payload, sort_keys=True), commit)


def read_notes(root) -> list:
    out = _git(root, "notes", f"--ref={NOTES_REF}", "list", check=False)
    notes = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        note_obj, target = parts
        body = _git(root, "cat-file", "-p", note_obj, check=False)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"raw": body}
        notes.append({"commit": target, "payload": payload})
    return notes


def orphaned_notes(root) -> list:
    """Notes whose commit is unreachable from any ref (e.g. after a rebase)."""
    reachable = set(_git(root, "rev-list", "--all", check=False).split())
    return [n for n in read_notes(root) if n["commit"] not in reachable]
