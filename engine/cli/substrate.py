"""Substrate read/write commands.

extract, resolve, gates, registry, merge-substrate, graph, memory and
status: the commands that read or mutate `.harness/` directly, without a
ceremony around them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from engine import get_slice, harness_dir, load_config, write_jsonl
from engine.cli.common import _acceptance_python, _print, _root, _session


# ------------------------------------------------------------------ extract
def cmd_extract(args):
    from engine.extractor.engine import (extract_all, extract_path, in_root,
                                         shadow_path_for)
    root = _root(args)
    config = load_config(root)
    if args.all:
        _print(extract_all(root, config, force=args.force))
        return 0
    if not args.paths:
        print("error: pass file paths or --all", file=sys.stderr)
        return 2
    # cache hits report under "cached", never "written" — the report must
    # not lie exactly when someone is debugging stale shadows (W7)
    out = {"written": [], "cached": [], "findings": []}
    for p in args.paths:
        target = Path(p).resolve()
        sp = shadow_path_for(root, target) if in_root(root, target) else None
        pre = sp.read_bytes() if sp and sp.exists() else None
        shadow, findings = extract_path(root, target, config, force=args.force)
        out["findings"].extend(findings)
        if shadow is None:
            continue
        post = sp.read_bytes() if sp and sp.exists() else None
        bucket = "written" if (args.force or pre != post) else "cached"
        out[bucket].append(shadow["source_path"])
    _print(out)
    return 0


# ------------------------------------------------------------------ resolve
def cmd_resolve(args):
    from engine.events import Sidecar
    from engine.resolver import resolve
    root = _root(args)
    config = load_config(root)
    out = resolve(root, args.slice, config)
    session = _session(args, root)
    # G2 certifies what the caller was SHOWN. Registering the manifest while
    # suppressing the injections would make the gate verify the resolver's
    # intent instead of the agent's context (review R3) — so --quiet, which
    # withholds the injections, withholds the registration too.
    if args.quiet:
        out["injections"] = []
        out["context_registered"] = 0
    else:
        sidecar = Sidecar(root)
        try:
            sidecar.context_add(session, out["context_loaded"])
        finally:
            sidecar.close()
        out["context_registered"] = len(out["context_loaded"])
    out["session"] = session
    # improvement 5: builders should not need the venv path plumbed by hand
    out["acceptance_python"] = _acceptance_python(root, config)
    _print(out)
    return 0


# ------------------------------------------------------------------ gates
def cmd_gates(args):
    root = _root(args)
    config = load_config(root)

    if args.gates_cmd == "override":
        from engine.gates.g5_conformance import record_override
        edge = record_override(root, args.slice, args.target,
                               args.justification, args.finding_id,
                               rule_ref=args.rule_ref)
        _print(edge)
        return 0
    if args.gates_cmd == "ack-drift":
        from engine.gates.g6_drift import acknowledge
        _print(acknowledge(root, args.slice, args.module, args.note or ""))
        return 0

    # run: synthesize an event and run its gate pack
    from engine.events import handle_event
    verdict = handle_event({
        "event": args.event,
        "session_id": _session(args, root),
        "work_unit_id": args.slice,
        "payload": {"files": [{"path": p, "proposed_content_hash": None}
                              for p in (args.files or [])],
                    "context_loaded": args.context or [],
                    "diff": None, "prompt": None},
    }, root)
    _print(verdict)
    return 0 if verdict["verdict"] != "block" else 1


# ------------------------------------------------------------------ registry
def cmd_registry(args):
    """Registry maintenance. `refresh <id>` re-derives a built entry's
    source_hash/signature_digest from its fresh shadow — the repair for
    hook-bypassing edits that left verify reporting HASH_MISMATCH (W11)."""
    from engine.registry import refresh_built
    root = _root(args)
    if args.registry_cmd == "refresh":
        _print(refresh_built(root, args.id))
    return 0


# ------------------------------------------------------------------ merge-substrate
def cmd_merge_substrate(args):
    """W5: git merge driver for keyed-by-id substrate JSONL (%O %A %B).
    Parallel worktree closes conflict on .harness rows by construction;
    the resolution is mechanical — per-id 3-way. A row both sides changed
    differently is a real conflict: exit 1, ours left for manual merge."""
    from engine import read_jsonl
    base = read_jsonl(args.base)
    ours = read_jsonl(args.ours)
    theirs = read_jsonl(args.theirs)
    for name, rows in (("base", base), ("ours", ours), ("theirs", theirs)):
        if any(not isinstance(r, dict) or "id" not in r for r in rows):
            print(f"error: {name} ({getattr(args, name)}) has rows without an "
                  f"'id' key — not mergeable by this driver", file=sys.stderr)
            return 1
        ids = [r["id"] for r in rows]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            # dict-keying would keep the LAST row per id: silent data loss
            print(f"error: {name} ({getattr(args, name)}) has duplicate ids "
                  f"{dupes} — refusing to merge (rows would be silently "
                  f"collapsed); dedupe the file first", file=sys.stderr)
            return 1
    b = {r["id"]: r for r in base}
    o = {r["id"]: r for r in ours}
    t = {r["id"]: r for r in theirs}
    order = list(dict.fromkeys([r["id"] for r in ours] +
                               [r["id"] for r in theirs]))
    merged, conflicts = [], []
    for rid in order:
        ov, tv, bv = o.get(rid), t.get(rid), b.get(rid)
        if rid in o and rid in t:
            if ov == tv:
                merged.append(ov)          # both agree (or both untouched)
            elif ov == bv:
                merged.append(tv)          # only theirs changed
            elif tv == bv:
                merged.append(ov)          # only ours changed
            else:
                conflicts.append(rid)
        elif rid in o:                      # absent from theirs
            if rid not in b:
                merged.append(ov)          # ours added it
            elif ov != bv:
                conflicts.append(rid)      # ours modified, theirs deleted
        else:                               # absent from ours
            if rid not in b:
                merged.append(tv)          # theirs added it
            elif tv != bv:
                conflicts.append(rid)      # theirs modified, ours deleted
    if conflicts:
        print(f"conflict: rows changed on both sides: {conflicts} — resolve "
              f"{args.ours} by hand and `git add` it", file=sys.stderr)
        return 1
    write_jsonl(args.ours, merged)
    _print({"merged": len(merged), "wrote": str(args.ours)})
    return 0


# ------------------------------------------------------------------ graph
def cmd_graph(args):
    from engine import graph
    root = _root(args)
    if args.graph_cmd == "neighbors":
        _print(graph.neighbors(root, args.node))
    elif args.graph_cmd == "provenance":
        _print(graph.provenance(root, args.module))
    elif args.graph_cmd == "uses-declares":
        _print(graph.uses_vs_declares(root, args.slice))
    elif args.graph_cmd == "note":
        # repair paths for a closed slice whose note was lost (deleted ref,
        # a close from before notes were enforced, a rewritten branch) or
        # whose commit a squash/rebase merge replaced (--repoint, D-010).
        if args.repoint:
            slice_id, commit = args.repoint
            _print(graph.repoint_note(root, slice_id,
                                      graph.resolve_commit(root, commit)))
            return 0
        if not (args.slice and args.commit):
            print("error: graph note needs --slice and --commit, or "
                  "--repoint <slice-id> <sha>", file=sys.stderr)
            return 2
        # rebuilt from substrate — the same source close-slice used.
        # A symbolic ref resolves to its sha first: a notes row keyed to the
        # literal "HEAD" resolves to nothing forever.
        payload = graph.slice_note_payload(root, args.slice)
        commit = graph.resolve_commit(root, args.commit)
        graph.write_note(root, commit, payload)
        _print({"note_written": True, "slice": args.slice,
                "commit": commit,
                "modules_touched": payload["modules_touched"]})
    elif args.graph_cmd == "edge":
        _print(graph.append_edge(root, args.type, args.frm, args.to,
                                 commit=args.commit,
                                 meta=json.loads(args.meta or "{}")))
    return 0


# ------------------------------------------------------------------ memory
def cmd_memory(args):
    from engine import memory, telemetry
    root = _root(args)
    if args.memory_cmd == "write":
        entry = memory.make_entry(
            args.slice, args.kind, args.content,
            attempt={"approach": args.approach, "outcome": args.outcome,
                     "why": args.why} if args.kind == "attempt" else None,
            edges=[{"type": "remembers", "to": t} for t in (args.edge or [])])
        _print(memory.write_entry(root, entry))
    elif args.memory_cmd == "flush":
        slice_id = args.slice
        if not slice_id and args.session:
            # resolve the session's bound slice from the sidecar
            from engine.events import Sidecar
            sidecar = Sidecar(root)
            try:
                slice_id = sidecar.state_get(args.session, "active_slice")
            finally:
                sidecar.close()
        result = memory.flush(root, slice_id)
        if args.compaction:
            # PreCompact: flush + COMPACTION_REACHED telemetry ONLY (§1.5).
            telemetry.emit(root, "COMPACTION_REACHED",
                           {"slice": slice_id, "session": args.session})
        _print(result)
    elif args.memory_cmd == "compact":
        _print(memory.compact_to_durable(root, args.slice, commit=args.commit))
    return 0


# ------------------------------------------------------------------ status
def cmd_status(args):
    from engine import telemetry
    root = _root(args)
    _print(telemetry.aggregate(root, since=args.since))
    return 0
