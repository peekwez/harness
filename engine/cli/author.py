"""Phase-0 authoring commands: architect, compile, author-gate, backlog, slice.

Authored artifacts (ADRs, contracts, the working document) become substrate
here, and slice rows are appended through `backlog add` rather than
hand-edited.
"""
from __future__ import annotations

import sys
from pathlib import Path

from engine import (HarnessError, harness_dir, load_backlog, load_config,
                    write_jsonl)
from engine.cli.common import _print, _root, _session
from engine.cli.slice import _bind_slice


DEFAULT_WORKING_DOC = "docs/architecture.md"


# ------------------------------------------------------------------ architect
def _under_root(root, path) -> Path:
    """Resolves a CLI path argument relative to the substrate root."""
    p = Path(path)
    return p if p.is_absolute() else Path(root) / p


def _rel(root, path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return str(path)


def cmd_architect(args):
    """Seeds the Phase-0 working document from an existing spec (D-013).

    A repo that already owns a spec must not have it re-derived Socratically:
    headings become `[constraint]` blocks, TODO/TBD/Open lines become
    `[open-question]`s, and the document opens at stage 3 (converge) with an
    empty `harness-decisions` table to fill in.

    Args:
        args: Parsed CLI args (`from_spec`, `doc`, `force`, `root`).

    Returns:
        Process exit code (0).

    Raises:
        HarnessError: The spec is missing, or the working document exists
            and `--force` was not given.
    """
    from engine.compiler import seed_doc_from_spec
    root = _root(args)
    spec = _under_root(root, args.from_spec)
    if not spec.is_file():
        raise HarnessError(f"--from-spec {args.from_spec!r} is not a readable "
                           f"file — nothing to seed the working document from")
    doc = _under_root(root, args.doc)
    if doc.exists() and not args.force:
        raise HarnessError(
            f"working document {_rel(root, doc)} already exists — edit it in "
            f"place (stage marker decides the stage), or re-run with --force "
            f"to overwrite it from {args.from_spec}")
    body = seed_doc_from_spec(spec.read_text(encoding="utf-8"),
                              _rel(root, spec))
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(body, encoding="utf-8")
    lines = body.splitlines()
    _print({"doc": str(doc), "spec": str(spec), "stage": 3,
            "constraints": sum(1 for ln in lines
                               if ln.startswith("[constraint] ")),
            "open_questions": sum(1 for ln in lines
                                  if ln.startswith("[open-question] "))})
    return 0


# ------------------------------------------------------------------ compile / author-gate
def cmd_compile(args):
    """Compiles authored artifacts into substrate.

    Warns (never silently skips) when the repo's working document carries
    typed `harness-*` tables but `--doc` was omitted: rows nobody compiled
    are exactly the silent degradation this engine exists to refuse.
    """
    from engine.compiler import compile_substrate
    from engine.docsections import mentions_typed_blocks
    root = _root(args)
    if not args.doc:
        doc = Path(root) / DEFAULT_WORKING_DOC
        if doc.exists() and mentions_typed_blocks(doc.read_text(encoding="utf-8")):
            print(f"warning: {DEFAULT_WORKING_DOC} carries harness-decisions/"
                  f"harness-abstractions tables that this run did NOT compile "
                  f"— re-run with --doc {DEFAULT_WORKING_DOC}", file=sys.stderr)
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
