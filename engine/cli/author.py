"""Phase-0 authoring commands: compile, author-gate, backlog, slice.

Authored artifacts (ADRs, contracts, the working document) become substrate
here, and slice rows are appended through `backlog add` rather than
hand-edited.
"""
from __future__ import annotations

import sys
from pathlib import Path

from engine import harness_dir, load_backlog, load_config, write_jsonl
from engine.cli.common import _print, _root, _session
from engine.cli.slice import _bind_slice


# ------------------------------------------------------------------ compile / author-gate
def cmd_compile(args):
    from engine.compiler import compile_substrate
    root = _root(args)
    _print(compile_substrate(root, working_doc=args.doc))
    return 0


def cmd_author_gate(args):
    from engine.compiler import author_gate
    root = _root(args)
    if args.doc and not Path(args.doc).exists():
        # a typo'd doc path must not silently skip the open-question check
        _print({"passed": False,
                "gaps": [f"working document {args.doc!r} does not exist"]})
        return 1
    result = author_gate(root, working_doc=args.doc)
    _print(result)
    return 0 if result["passed"] else 1


# ------------------------------------------------------------------ backlog
def _backlog_add(args):
    """imp-3: slice rows were the last hand-edited substrate (the historical
    EDIT-ME defect source) — append them through the CLI, validated."""
    from engine.registry import load_registry
    from engine.resolver import context_cost_estimate
    root = _root(args)
    config = load_config(root)
    rows = load_backlog(root)
    if any(r.get("id") == args.id for r in rows):
        print(f"error: slice {args.id!r} already exists in backlog.jsonl",
              file=sys.stderr)
        return 1
    known = {e["id"] for e in load_registry(root)}
    unknown = sorted(d for d in (args.declares or []) if d not in known)
    if unknown:
        print(f"error: declares_dep names unknown registry entries "
              f"{unknown} — add the abstraction to an ADR and recompile, "
              f"or fix the id", file=sys.stderr)
        return 1
    row = {"id": args.id, "spec": args.spec,
           "title": args.title or args.id, "status": "planned",
           "declares_dep": list(args.declares or []),
           "acceptance": list(args.acceptance),
           "predicted_files": list(dict.fromkeys(
               (args.predicts or []) + list(args.acceptance))),
           "depends_on": list(args.depends or []), "worktree": None}
    row["context_cost_estimate"] = context_cost_estimate(
        root, row["declares_dep"], config)
    rows.append(row)
    write_jsonl(harness_dir(root) / "backlog.jsonl", rows)
    _print(row)
    return 0


def cmd_backlog(args):
    if getattr(args, "backlog_cmd", None) == "add":
        return _backlog_add(args)
    from engine.resolver import context_cost_estimate
    root = _root(args)
    config = load_config(root)
    budget = int(config["resolver"]["budget_tokens"])
    limit = budget * 0.8
    rows = load_backlog(root)
    out, split = [], []
    for s in rows:
        # acceptance paths are implicitly predicted: every slice writes its
        # own acceptance test — declaring it twice is ceremony, not discipline
        s["predicted_files"] = list(dict.fromkeys(
            s.get("predicted_files", []) + s.get("acceptance", [])))
        est = context_cost_estimate(root, s.get("declares_dep", []), config)
        s["context_cost_estimate"] = est
        if est > limit and len(s.get("declares_dep", [])) > 1 and args.split:
            deps = s["declares_dep"]
            mid = max(1, len(deps) // 2)
            for suffix, part in (("a", deps[:mid]), ("b", deps[mid:])):
                child = dict(s)
                child["id"] = f"{s['id']}-{suffix}"
                child["title"] = f"{s.get('title', s['id'])} ({suffix})"
                child["declares_dep"] = part
                child["context_cost_estimate"] = context_cost_estimate(root, part, config)
                if suffix == "b":
                    child["depends_on"] = list(dict.fromkeys(
                        (s.get("depends_on") or []) + [f"{s['id']}-a"]))
                out.append(child)
            split.append(s["id"])
        else:
            out.append(s)
    write_jsonl(harness_dir(root) / "backlog.jsonl", out)
    _print({"slices": [s["id"] for s in out], "split": split,
            "budget": budget, "limit": limit})
    return 0


# ------------------------------------------------------------------ slice / close-slice
def cmd_slice(args):
    from engine.events import Sidecar
    from engine.graph import append_edge, load_edges
    root = _root(args)
    if args.release:
        sidecar = Sidecar(root)
        try:
            n = sidecar.release_slice(args.slice if args.slice else None)
        finally:
            sidecar.close()
        _print({"released": n, "slice": args.slice or "all"})
        return 0
    if not args.slice:
        print("error: --slice required (or --release)", file=sys.stderr)
        return 2
    _print(_bind_slice(root, args.slice, _session(args, root)))
    return 0
