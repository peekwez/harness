"""C4 — Graph store: append-only edges.jsonl + git-notes mirror.

Edges are never updated; a newer event supersedes. The graph is rebuildable
from the log alone. Node IDs are stable logical IDs; commits are the only
nodes whose ID is their hash.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import (HarnessError, append_jsonl, harness_dir, now_iso,
               read_jsonl, sha256_text)

EDGE_TYPES = {"implements", "declares_dep", "uses", "shadows", "supersedes",
              "governs", "decided_by", "satisfies", "produced_by", "touches",
              "reviewed_by",
              "remembers", "override"}

NOTES_REF = "refs/notes/harness"

# The second key (ADR-002 / D-010): a derived, append-only log of every note
# ever written, keyed by {slice_id, tree_hash}. A squash or rebase merge
# rewrites the commit a note is attached to, but the CONTENT it landed keeps
# its tree hash — so verify resolves the slice by tree hash instead of
# reporting an orphan forever. Union-merged like every append-only log, and
# never regenerated: history cannot be re-derived.
NOTES_LOG = "notes.jsonl"


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


def _note_payloads(body: str) -> list:
    """Normalize a note body to a list of slice payloads. Legacy notes hold
    a single object; current ones hold an array, because a commit can carry
    more than one slice (squash merges, repaired history)."""
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return [{"raw": body}]
    return parsed if isinstance(parsed, list) else [parsed]


def notes_log_path(root) -> Path:
    """Path of the derived notes log (`.harness/notes.jsonl`)."""
    return harness_dir(root) / NOTES_LOG


def tree_hash(root, commit: str):
    """The tree a commit points at, or None when it cannot be resolved."""
    out = _git(root, "rev-parse", f"{commit}^{{tree}}", check=False).strip()
    return out or None


def source_key(root, commit: str):
    """Digest of a commit's tree with `.harness` excluded, or None.

    A slice branch ends with the ceremony's own substrate commit, so the
    commit a squash merge produces never reproduces the NOTED commit's whole
    tree — but it does reproduce its source tree, because the substrate
    commit touches nothing outside `.harness`. Hashing the top-level tree
    entries minus `.harness` is therefore the key that survives the squash,
    and every entry's sha covers its whole subtree.

    Args:
        root: Substrate root.
        commit: Commit-ish to key.

    Returns:
        `sha256:<hex>` over the filtered top-level tree entries, or None.
    """
    listing = _git(root, "ls-tree", f"{commit}^{{tree}}", check=False)
    if not listing.strip():
        return None
    kept = sorted(line for line in listing.splitlines()
                  if line.strip() and line.split("\t")[-1] != ".harness")
    return sha256_text("\n".join(kept))


def record_tree(root, slice_id: str, commit: str) -> dict:
    """Append one `{ts, slice_id, commit, tree_hash, source_tree}` row.

    Args:
        root: Substrate root.
        slice_id: The slice whose provenance this row keys.
        commit: The commit whose tree is recorded.

    Returns:
        The appended row (hashes are None outside a git repo).
    """
    row = {"ts": now_iso(), "slice_id": slice_id, "commit": commit,
           "tree_hash": tree_hash(root, commit),
           "source_tree": source_key(root, commit)}
    append_jsonl(notes_log_path(root), row)
    return row


def notes_log(root, slice_id=None) -> list:
    """Rows of the derived notes log, optionally for one slice."""
    rows = read_jsonl(notes_log_path(root))
    return [r for r in rows if slice_id is None or r.get("slice_id") == slice_id]


def write_note(root, commit, payload: dict) -> dict:
    """Mirror {slice_id, modules_touched, registry_used, memory_ids} onto the
    commit so provenance travels with the repo. Additive: a second slice on
    the same commit joins the note instead of overwriting it (`notes add -f`
    silently erased the first one); re-noting the same slice replaces its
    own entry. The same write is keyed a second time into the derived notes
    log by tree hash (D-010), which is what survives a squash merge.

    Args:
        root: Substrate root.
        commit: The commit to annotate.
        payload: The slice's provenance payload.

    Returns:
        The notes-log row `{ts, slice_id, commit, tree_hash}`.
    """
    existing = _git(root, "notes", f"--ref={NOTES_REF}", "show", commit,
                    check=False).strip()
    payloads = [p for p in (_note_payloads(existing) if existing else [])
                if p.get("slice_id") != payload.get("slice_id")]
    payloads.append(payload)
    payloads.sort(key=lambda p: str(p.get("slice_id")))
    _git(root, "notes", f"--ref={NOTES_REF}", "add", "-f", "-m",
         json.dumps(payloads, sort_keys=True), commit)
    return record_tree(root, str(payload.get("slice_id")), commit)


def slice_note_payload(root, slice_id: str) -> dict:
    """Rebuild a slice's note payload from substrate.

    The same source `close-slice` used, so the repair paths (`graph note`,
    `graph note --repoint`) write the note the ceremony would have written.

    Args:
        root: Substrate root.
        slice_id: The slice to describe.

    Returns:
        `{slice_id, modules_touched, registry_used, memory_ids}`.
    """
    from . import get_slice
    sl = get_slice(root, slice_id)
    touched = sorted(e["to"].split(":", 1)[1] for e in load_edges(root)
                     if e["type"] == "touches"
                     and e["from"] == f"slice:{slice_id}")
    durable = read_jsonl(harness_dir(root) / "memory" / "durable.jsonl")
    return {"slice_id": slice_id, "modules_touched": touched,
            "registry_used": sl.get("declares_dep", []),
            "memory_ids": [m["id"] for m in durable
                           if m.get("slice") == slice_id]}


def last_note_payload(root, slice_id: str) -> dict:
    """The payload a slice's most recent note carried, or a rebuilt one.

    Args:
        root: Substrate root.
        slice_id: The slice to look up.

    Returns:
        The payload recorded on the newest notes-log commit that still has a
        readable note, else the substrate-rebuilt payload.
    """
    for row in reversed(notes_log(root, slice_id)):
        body = _git(root, "notes", f"--ref={NOTES_REF}", "show",
                    str(row.get("commit")), check=False).strip()
        if not body:
            continue
        for payload in _note_payloads(body):
            if payload.get("slice_id") == slice_id:
                return payload
    return slice_note_payload(root, slice_id)


def repoint_note(root, slice_id: str, commit: str) -> dict:
    """Re-attach a slice's provenance note to `commit` (D-010).

    The repair after a squash or rebase merge rewrote the sha the note was
    written on. The payload is the one the slice's last note carried, so a
    repoint never invents provenance.

    Args:
        root: Substrate root.
        slice_id: The slice whose note moves.
        commit: The commit that now carries the slice's content.

    Returns:
        `{note_written, slice, commit, tree_hash, payload}`.
    """
    payload = dict(last_note_payload(root, slice_id))
    payload["slice_id"] = slice_id
    row = write_note(root, commit, payload)
    return {"note_written": True, "slice": slice_id, "commit": commit,
            "tree_hash": row.get("tree_hash"), "payload": payload}


def read_notes(root) -> list:
    """[{commit, payloads: [...], payload: <first, legacy accessor>}]"""
    out = _git(root, "notes", f"--ref={NOTES_REF}", "list", check=False)
    notes = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        note_obj, target = parts
        payloads = _note_payloads(_git(root, "cat-file", "-p", note_obj,
                                       check=False))
        notes.append({"commit": target, "payloads": payloads,
                      "payload": payloads[0] if payloads else {}})
    return notes


def orphaned_notes(root) -> list:
    """Notes whose commit is unreachable from any ref (e.g. after a rebase)."""
    reachable = set(_git(root, "rev-list", "--all", check=False).split())
    return [n for n in read_notes(root) if n["commit"] not in reachable]


# The walk is capped: a provenance lookup must never turn into a full-history
# scan in a repo with a hundred thousand commits. A slice lands near the tip.
TREE_WALK_LIMIT = 5000


# The source-key scan costs one `git ls-tree` per commit, so it is lazy and
# walks a much shorter window than the cheap tree-hash walk: a slice lands at
# the tip, not a thousand commits back.
SOURCE_WALK_LIMIT = 200


def _walk_revs(root, base=None, remote=None) -> list:
    """The refs a provenance walk covers.

    `landing.base` when it exists locally, its remote-tracking ref (a
    developer who never checks the base branch out still has `origin/main`),
    and HEAD. Never `--all`: a slice sitting on an unmerged branch has not
    landed.

    Args:
        root: Substrate root.
        base: The base branch name.
        remote: `landing.remote`, for the remote-tracking ref.

    Returns:
        The refs that exist, in walk order.
    """
    candidates = [base, f"{remote or 'origin'}/{base}" if base else None, "HEAD"]
    revs = []
    for rev in candidates:
        if rev and rev not in revs and _git(root, "rev-parse", "--verify",
                                            "--quiet", rev, check=False).strip():
            revs.append(rev)
    return revs


def reachable_trees(root, base=None, max_count=TREE_WALK_LIMIT,
                    remote=None) -> dict:
    """Map every reachable commit's tree hash to that commit.

    Args:
        root: Substrate root.
        base: Ref to walk (`landing.base`); its remote-tracking ref and
            HEAD are walked too.
        max_count: Cap on the walk.
        remote: `landing.remote`, for the remote-tracking ref.

    Returns:
        `{tree_hash: commit_sha}`, newest commit wins per tree.
    """
    revs = _walk_revs(root, base, remote)
    if not revs:
        return {}
    out = _git(root, "log", f"--max-count={int(max_count)}", "--format=%H %T",
               *revs, check=False)
    trees = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2:
            trees.setdefault(parts[1], parts[0])
    return trees


def reachable_source_keys(root, base=None, max_count=SOURCE_WALK_LIMIT,
                          remote=None) -> dict:
    """`{source_key: commit}` for the newest reachable commits.

    Args:
        root: Substrate root.
        base: Ref to walk alongside its remote-tracking ref and HEAD.
        max_count: Cap on the walk (one `git ls-tree` per commit).
        remote: `landing.remote`, for the remote-tracking ref.

    Returns:
        Mapping of source key to the newest commit carrying it.
    """
    revs = _walk_revs(root, base, remote)
    if not revs:
        return {}
    out = _git(root, "log", f"--max-count={int(max_count)}", "--format=%H",
               *revs, check=False)
    keys = {}
    for commit in out.split():
        key = source_key(root, commit)
        if key:
            keys.setdefault(key, commit)
    return keys


def resolve_note(root, slice_id: str, trees: dict, source_keys=None):
    """Resolve a slice's provenance against the derived notes log (D-010).

    Notes are keyed twice — on the commit and in `.harness/notes.jsonl` by
    `{slice_id, tree_hash}`. A squash or rebase merge rewrites the commit a
    note was written on, but not the content it landed: a recorded tree that
    is still reachable IS the provenance, and no orphan finding is due. Two
    keys are tried, exact first — the whole tree (a rebase-replayed or
    cherry-picked commit reproduces it) and then the source tree with
    `.harness` excluded (what a squash of a slice branch reproduces, since
    the ceremony's substrate commit rides in the same squash).

    Args:
        root: Substrate root.
        slice_id: The slice to resolve.
        trees: `reachable_trees()` output.
        source_keys: `reachable_source_keys()` output, or a zero-argument
            callable returning it (so the costlier walk stays lazy).

    Returns:
        `{resolved_via: "tree_hash", commit}` or None when nothing resolves
        the slice — which is the finding the caller already had.
    """
    rows = notes_log(root, slice_id)
    if not rows:
        return None
    for row in reversed(rows):
        commit = trees.get(row.get("tree_hash"))
        if commit:
            return {"resolved_via": "tree_hash", "commit": commit,
                    "key": "tree"}
    keys = source_keys() if callable(source_keys) else (source_keys or {})
    for row in reversed(rows):
        commit = keys.get(row.get("source_tree"))
        if commit:
            return {"resolved_via": "tree_hash", "commit": commit,
                    "key": "source_tree"}
    return None
