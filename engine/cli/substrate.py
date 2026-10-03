"""Substrate read/write commands.

extract, resolve, gates, registry, merge-substrate, graph, memory,
precompact and status: the commands that read or mutate `.harness/` directly, without a
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
    from engine.resolver import render_module, resolve
    root = _root(args)
    if args.reset:
        from engine.events import Sidecar
        session = _session(args, root)
        sidecar = Sidecar(root)
        try:
            cleared = sidecar.block_hashes_clear(session)
        finally:
            sidecar.close()
        _print({"reset": True, "session": session, "cleared": cleared})
        return 0
    config = load_config(root)
    if args.module:
        _print(render_module(root, args.module, config))
        return 0
    out = resolve(root, args.slice, config, cap=None)
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
    """Shared memory (D-0.10-02). `promote` copies one fact into
    `.claude/memory/shared/`; the permit layer always asks a human first.
    `changed` lists personal memory files changed since a slice started."""
    from datetime import datetime, timezone
    from engine import shared_memory
    root = _root(args)
    if args.memory_cmd == "promote":
        if bool(args.file) == bool(args.text):
            print("error: memory promote: pass one fact. "
                  "Fix: give a file or --text \"<fact>\".", file=sys.stderr)
            return 2
        source = None
        if args.file:
            source = Path(args.file).expanduser()
            if not source.is_absolute():
                source = Path.cwd() / source
        _print(shared_memory.promote(root, source=source, text=args.text,
                                     name=args.name))
        return 0
    if args.since:
        try:
            stamp = datetime.fromisoformat(args.since.replace("Z", "+00:00"))
        except ValueError:
            print("error: memory changed: --since is not an ISO time. "
                  "Fix: pass e.g. 2026-10-02T09:00:00Z.", file=sys.stderr)
            return 2
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        since = stamp.timestamp()
    elif args.slice:
        since = shared_memory.slice_started_epoch(root, args.slice)
    else:
        print("error: memory changed: no start given. "
              "Fix: pass --slice <id> or --since <ISO time>.", file=sys.stderr)
        return 2
    directory = shared_memory.personal_memory_dir(root)
    _print({"dir": str(directory),
            "since": datetime.fromtimestamp(since, timezone.utc).isoformat(),
            "files": shared_memory.changed_since(directory, since)})
    return 0


# ------------------------------------------------------------------ precompact
def cmd_precompact(args):
    """PreCompact hook duty, for every host adapter: clear this session's
    per-block context hashes, so the next prompt injects once again (7.4),
    and count the compaction (D-0.10-11). Never injects anything. A failed
    clear still records the compaction, then exits 1."""
    from engine import telemetry
    from engine.events import Sidecar
    root = _root(args)
    session = _session(args, root)
    sidecar = Sidecar(root)
    failure = None
    try:
        slice_id = (sidecar.state_get(session, "active_slice")
                    or sidecar.state_get("__default__", "active_slice"))
        try:
            sidecar.block_hashes_clear(session)
        except Exception as exc:  # noqa: BLE001 - reported below, never lost
            failure = exc
    finally:
        sidecar.close()
    telemetry.emit(root, "COMPACTION_REACHED",
                   {"slice": slice_id, "session": session})
    if failure is not None:
        print(f"error: context reset failed: {failure}", file=sys.stderr)
        return 1
    _print({"compaction_recorded": True, "session": session, "slice": slice_id})
    return 0


# ------------------------------------------------------------------ status
def cmd_status(args):
    from engine import telemetry
    from engine.context_cost import always_on_cost
    root = _root(args)
    report = telemetry.status(root, since=args.since)
    report["always_on"] = always_on_cost(root)
    _print(report)
    return 0
