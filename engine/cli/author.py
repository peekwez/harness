"""Phase-0 authoring commands: architect, compile, author-gate, backlog, slice.

Authored artifacts (ADRs, contracts, the working document) become substrate
here, and slice rows are appended through `backlog add` rather than
hand-edited.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from engine import (HarnessError, harness_dir, load_backlog, load_config,
                    write_jsonl)
from engine.cli.common import _print, _root, _session
from engine.cli.slice import _bind_slice


DEFAULT_WORKING_DOC = "docs/architecture.md"
#: tracker ids a slice row may carry (`linear`, schema §5.6). Deliberately
#: narrow: the id is interpolated into a PR title and a Linear URL, so a
#: free-form string would produce a dead link nobody notices.
LINEAR_ID = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")


# ------------------------------------------------------------------ architect
def _under_root(root, path) -> Path:
    """Resolves a CLI path argument relative to the substrate root."""
    p = Path(path)
    return p if p.is_absolute() else Path(root) / p


def _require_doc(root, doc) -> Path:
    """Resolve a `--doc` argument under the substrate root, fail loud if absent.

    Args:
        root: Substrate root.
        doc: The path as typed on the command line.

    Returns:
        The resolved path.

    Raises:
        HarnessError: The document does not exist — a typo must never
            silently skip the rows it was supposed to compile.
    """
    path = _under_root(root, doc)
    if not path.is_file():
        raise HarnessError(
            f"--doc {doc!r} does not exist (looked in {path}) — a working "
            f"document nobody compiled is exactly the silent degradation "
            f"this engine refuses")
    return path


def validate_linear(value: str) -> str:
    """Validate a tracker id for a slice row's `linear` field.

    Args:
        value: The id as typed (`GOO-73`).

    Returns:
        The stripped id.

    Raises:
        HarnessError: The id is not `<PROJECT>-<number>`.
    """
    linear = (value or "").strip()
    if not LINEAR_ID.match(linear):
        raise HarnessError(
            f"--linear {value!r} is not a tracker id like 'GOO-73' "
            f"(uppercase project key, dash, digits) — it is interpolated "
            f"into the PR title and the issue URL")
    return linear


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
    doc = None
    if args.doc:
        doc = _require_doc(root, args.doc)
    else:
        default = Path(root) / DEFAULT_WORKING_DOC
        if default.exists() and mentions_typed_blocks(
                default.read_text(encoding="utf-8")):
            print(f"warning: {DEFAULT_WORKING_DOC} carries harness-decisions/"
                  f"harness-abstractions tables that this run did NOT compile "
                  f"— re-run with --doc {DEFAULT_WORKING_DOC}", file=sys.stderr)
    _print(compile_substrate(root, working_doc=doc))
    return 0


def cmd_author_gate(args):
    from engine.compiler import author_gate
    root = _root(args)
    # unlike compile, a missing doc is NOT an error here: the gate itself
    # reports it as a gap (fresh repos run this before the doc can exist —
    # the architect/backlog skill preambles). A typo'd path still fails the
    # gate loudly with the path named; nothing is silently skipped.
    doc = _under_root(root, args.doc) if args.doc else None
    result = author_gate(root, working_doc=doc)
    _print(result)
    # --report: verdict emitted -> exit 0 (semantics in JSON). The skill
    # preambles use it because gaps are the NORMAL state through stages 1-4
    # and a nonzero exit renders as a shell error in the host UI.
    if getattr(args, "report", False):
        return 0
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
    if getattr(args, "linear", None):
        row["linear"] = validate_linear(args.linear)
    row["context_cost_estimate"] = context_cost_estimate(
        root, row["declares_dep"], config)
    rows.append(row)
    write_jsonl(harness_dir(root) / "backlog.jsonl", rows)
    _print(row)
    return 0


def cmd_backlog(args):
    if getattr(args, "backlog_cmd", None) == "add":
        return _backlog_add(args)
    from engine.resolver import context_cost_breakdown
    root = _root(args)
    config = load_config(root)
    budget = int(config["resolver"]["budget_tokens"])
    limit = budget * 0.8
    rows = load_backlog(root)
    # who depends on whom: replacing a parent with -a/-b would leave every
    # dependent's `depends_on` pointing at a row that no longer exists
    dependents: dict = {}
    for r in rows:
        for d in r.get("depends_on") or []:
            dependents.setdefault(d, []).append(r["id"])
    out, split, refused, proposals, estimates = [], [], [], [], {}

    # Work out every split candidate and reserve its proposed ids before
    # changing backlog.jsonl.  A collision must leave even routine estimate
    # updates unwritten: otherwise a rejected split still mutates substrate.
    breakdowns = {}
    candidates = []
    for s in rows:
        breakdown = context_cost_breakdown(root, s.get("declares_dep", []),
                                           config)
        breakdowns[s["id"]] = breakdown
        oversized = (breakdown["total"] > limit
                     and len(s.get("declares_dep", [])) > 1)
        if (args.split and oversized and s.get("status") == "planned"
                and not dependents.get(s["id"])):
            candidates.append(s)
    existing_ids = {s["id"] for s in rows}
    for s in candidates:
        child_ids = [f"{s['id']}-a", f"{s['id']}-b"]
        collisions = sorted(set(child_ids) & existing_ids)
        if collisions:
            reason = (f"cannot propose split for {s['id']}: generated child "
                      f"id(s) {collisions} already exist; choose fresh ids "
                      f"and author the child contracts explicitly")
            _print({"slices": [row["id"] for row in rows], "split": [],
                    "split_refused": [{"id": s["id"], "reason": reason}],
                    "split_proposals": [], "estimates": breakdowns,
                    "budget": budget, "limit": limit, "reason": reason})
            return 1

    for s in rows:
        s = dict(s)
        breakdown = breakdowns[s["id"]]
        est = breakdown["total"]
        s["context_cost_estimate"] = est
        estimates[s["id"]] = breakdown
        oversized = est > limit and len(s.get("declares_dep", [])) > 1
        if not (args.split and oversized):
            # acceptance paths are implicitly predicted during ordinary
            # estimation.  A refused split keeps the parent's authored work
            # contract byte-for-byte equivalent apart from its estimate.
            s["predicted_files"] = list(dict.fromkeys(
                s.get("predicted_files", []) + s.get("acceptance", [])))
        if oversized and args.split and s.get("status") != "planned":
            # closed work is provenance, bound/parked work is someone's
            # context: neither is rewritten opportunistically
            refused.append({"id": s["id"],
                            "reason": f"status {s.get('status')}: only "
                                      f"planned slices are split"})
            out.append(s)
        elif oversized and args.split and dependents.get(s["id"]):
            refused.append({"id": s["id"],
                            "reason": f"depended on by "
                                      f"{sorted(dependents[s['id']])}: "
                                      f"splitting would dangle their "
                                      f"depends_on — split by hand and "
                                      f"repoint them"})
            out.append(s)
        elif oversized and args.split:
            deps = s["declares_dep"]
            mid = max(1, len(deps) // 2)
            child_ids = [f"{s['id']}-a", f"{s['id']}-b"]
            reason = ("automatic split refused: child slices require authored "
                      "acceptance and predicted_files contracts; add the "
                      f"proposed children {child_ids} explicitly after "
                      "partitioning their work scopes")
            proposal = {
                "id": s["id"], "child_ids": child_ids,
                "declares_dep": [deps[:mid], deps[mid:]], "reason": reason,
            }
            proposals.append(proposal)
            refused.append({"id": s["id"], "reason": reason})
            out.append(s)
        else:
            out.append(s)
    write_jsonl(harness_dir(root) / "backlog.jsonl", out)
    _print({"slices": [s["id"] for s in out], "split": split,
            "split_refused": refused, "split_proposals": proposals,
            "estimates": estimates,
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
    result = _bind_slice(root, args.slice, _session(args, root))
    code = result.pop("_exit_code", 0)
    _print(result)
    return code
