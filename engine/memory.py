"""§8 — Memory model.

Working memory (session scope): per-slice JSONL, flushed at every Stop.
`kind: attempt` is mandatory whenever an approach is abandoned mid-slice —
the replacement for what conversation compaction would have preserved.
Durable memory: promoted at close-slice and at adjudication.
PreCompact: flush + COMPACTION_REACHED telemetry only — compaction is a
defect signal, not an event to handle gracefully.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import HarnessError, append_jsonl, harness_dir, now_iso, read_jsonl

KINDS = {"reasoning", "attempt", "adjudication", "observation"}


def session_path(root, slice_id: str) -> Path:
    return harness_dir(root) / "memory" / "session" / f"{slice_id}.jsonl"


def durable_path(root) -> Path:
    return harness_dir(root) / "memory" / "durable.jsonl"


def make_entry(slice_id, kind, content, attempt=None, edges=None, commit=None) -> dict:
    if kind not in KINDS:
        raise HarnessError(f"memory kind {kind!r} invalid; expected {sorted(KINDS)}")
    if kind == "attempt":
        attempt = attempt or {}
        for req in ("approach", "outcome", "why"):
            if not attempt.get(req):
                raise HarnessError(
                    f"attempt entries require '{req}' — attempts are the replacement "
                    f"for what compaction would have preserved (fail closed)")
        if attempt["outcome"] not in ("failed", "abandoned", "partial"):
            raise HarnessError(f"attempt outcome {attempt['outcome']!r} invalid")
    mid = "mem-" + hashlib.sha1(
        f"{slice_id}|{kind}|{content}|{now_iso()}".encode()).hexdigest()[:12]
    return {"id": mid, "scope": "session", "slice_id": slice_id,
            "commit": commit, "kind": kind, "content": content,
            "attempt": attempt, "edges": list(edges or [])}


def write_entry(root, entry: dict) -> dict:
    append_jsonl(session_path(root, entry["slice_id"]), entry)
    return entry


def read_session(root, slice_id: str) -> list:
    return read_jsonl(session_path(root, slice_id))


def compact_to_durable(root, slice_id: str, commit=None) -> dict:
    """Promote session memory to durable, then delete the session file.
    Attempts and adjudications always survive; reasoning survives when marked
    or when it carries module edges."""
    from .graph import append_edge
    entries = read_session(root, slice_id)
    promoted = []
    for e in entries:
        keep = (e.get("kind") in ("attempt", "adjudication") or
                e.get("promote") or e.get("edges"))
        if not keep:
            continue
        d = dict(e)
        d["scope"] = "durable"
        d["commit"] = d.get("commit") or commit
        append_jsonl(durable_path(root), d)
        promoted.append(d["id"])
        for edge in d.get("edges", []):
            append_edge(root, edge.get("type", "remembers"),
                        f"memory:{d['id']}", edge["to"], commit=d["commit"])
    if entries:
        summary = {
            "id": "mem-" + hashlib.sha1(f"{slice_id}|summary|{len(entries)}".encode()).hexdigest()[:12],
            "scope": "durable", "slice_id": slice_id, "commit": commit,
            "kind": "observation",
            "content": f"slice {slice_id}: {len(entries)} working-memory entries, "
                       f"{len(promoted)} promoted "
                       f"({sum(1 for e in entries if e.get('kind') == 'attempt')} attempts)",
            "attempt": None,
            "edges": [{"type": "remembers", "to": f"slice:{slice_id}"}],
        }
        append_jsonl(durable_path(root), summary)
        append_edge(root, "remembers", f"memory:{summary['id']}", f"slice:{slice_id}",
                    commit=commit)
    sp = session_path(root, slice_id)
    if sp.exists():
        sp.unlink()
    return {"promoted": promoted, "total": len(entries)}


def flush(root, slice_id: str | None) -> dict:
    """PreCompact duty: session memory is already durable-on-write (JSONL), so
    flush verifies the file is on disk and records the defect signal upstream."""
    if slice_id:
        sp = session_path(root, slice_id)
        return {"flushed": str(sp), "entries": len(read_jsonl(sp))}
    return {"flushed": None, "entries": 0}
