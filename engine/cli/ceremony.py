"""The close ceremony: every precondition a slice must clear to close.

Kept apart from `engine.cli.close` because the ceremony is one long ordered
sequence of preconditions and the commands around it are not.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from engine import (HarnessError, get_slice, harness_dir, load_config,
                    save_slice)
from engine.cli.acceptance import GATE_REASON, gate_finding
from engine.cli.common import _fail, _reset_close_attempts, _root, _session
from engine.cli.slice import _acceptance_green


DEP_MANIFESTS = ("requirements.txt", "requirements-dev.txt",
                 "pyproject.toml", "setup.py", "setup.cfg", "package.json",
                 "Cargo.toml", "go.mod")


def _added_dependency_lines(root, sl, commit) -> dict:
    """{manifest: [added lines]} between the slice anchor and its commit.
    Comments/blank lines are ignored; parsing every ecosystem's semantics is
    not attempted — an added line in a manifest IS the signal."""
    import subprocess
    base = sl.get("started_at_commit")
    rng = f"{base}..{commit}" if base else f"{commit}^!"
    proc = subprocess.run(["git", "-C", str(root), "diff", rng, "--",
                          *DEP_MANIFESTS],
                         capture_output=True, text=True)
    if proc.returncode != 0:
        return {}
    added, current = {}, None
    for line in proc.stdout.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
        elif (line.startswith("+") and not line.startswith("+++")
              and current is not None):
            body = line[1:].strip()
            if body and not body.startswith(("#", "//", ";")):
                added.setdefault(current, []).append(body[:120])
    return added


def _security_rows_for_slice(root, sl):
    """Decision rows with security: true that resolve for this slice —
    domain matches the declared deps' ids/kinds, or (no deps declared) all
    rows join, mirroring the resolver's routing (ADR-001)."""
    from engine import load_decisions
    from engine.registry import load_registry
    deps = sl.get("declares_dep", [])
    registry = {e["id"]: e for e in load_registry(root)}
    domain_keys = set(deps) | {registry[d].get("kind") for d in deps
                               if d in registry}
    return sorted(d["id"] for d in load_decisions(root)
                  if d.get("security")
                  and (not domain_keys or d.get("domain") in domain_keys))


def _close_ceremony(args):
    from engine.events import Sidecar, handle_event
    from engine.gates.g3_scope import SUBSTRATE_PREFIXES
    from engine.graph import (append_edge, load_edges, uses_vs_declares,
                              write_note, GraphError)
    from engine.registry import flip_status, load_registry, RegistryError
    from engine import memory, telemetry
    root = _root(args)
    config = load_config(root)
    session = _session(args, root)
    sl = get_slice(root, args.slice)

    # Re-closing re-runs the whole ceremony (duplicate telemetry, note
    # rewrite, fresh substrate commit) — refuse (S10). Guards are not
    # attempts: they must never push a slice toward auto-park.
    if sl.get("status") == "closed":
        _fail({"closed": False,
                "reason": f"slice {args.slice} is already closed"},
              attempt=False)
    if sl.get("status") == "parked":
        _fail({"closed": False,
                "reason": f"slice {args.slice} is parked: "
                          f"{sl.get('parked_reason', '(no reason recorded)')} "
                          f"— a human re-binds (`harness slice --slice "
                          f"{args.slice}`) to unpark",
                "rule_ref": "gate:G1"}, attempt=False)

    # Symbolic --commit refs (HEAD, branch names) resolve to the stable sha
    # up front: provenance rows and notes must never carry a moving ref, and
    # `--commit $(git rev-parse HEAD)` substitution defeats permission
    # auto-approval — `--commit HEAD` is the prompt-free spelling.
    if args.commit and (root / ".git").exists():
        import subprocess
        rp = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify",
                             args.commit], capture_output=True, text=True)
        if rp.returncode == 0:
            args.commit = rp.stdout.strip()

    # Precondition 0: no scaffold placeholders ratify by inertia.
    from engine.compiler import PLACEHOLDER_SENTINEL
    if PLACEHOLDER_SENTINEL in json.dumps(sl):
        _fail({"closed": False,
                "reason": f"slice {args.slice} still contains the scaffold "
                          f"'{PLACEHOLDER_SENTINEL}' placeholder — edit the "
                          f"backlog row before closing"})

    # Precondition 1: acceptance green (engine-enforced, §7.5 / §1.4).
    green, evidence = _acceptance_green(root, sl, config)
    if not green:
        reason = "acceptance tests are not green"
        if str(evidence).startswith("cumulative regression"):
            reason = str(evidence).splitlines()[0]
        _fail({"closed": False, "reason": reason, "evidence": evidence})

    # Precondition 1.1 (D-012): the repo's own whole-tree gate (`make check`
    # and friends) runs ONCE here — acceptance green, substrate not yet
    # committed — and its non-zero exit blocks the close.
    gate, gate_tail = gate_finding(root, config)
    if gate is not None:
        _fail({"closed": False, "rule_ref": gate["rule_ref"],
                "reason": GATE_REASON, "evidence": gate_tail,
                "findings": [gate]})

    # Precondition 1.5 — ADR-001: a slice resolving any security-marked
    # decision row needs an INDEPENDENT forked reviewer's pass verdict.
    # The engine stack catches rule violations; the seed-leak class of
    # catch only ever came from a fresh-context LLM reviewer.
    fork_review = None
    if config.get("review", {}).get("fork_for_security_rows", True):
        sec_rows = _security_rows_for_slice(root, sl)
        if sec_rows:
            fork_review = "required"
            from engine.graph import load_edges
            forks = [e for e in load_edges(root)
                     if e["from"] == f"slice:{args.slice}"
                     and e["type"] == "reviewed_by"
                     and e.get("meta", {}).get("kind") == "fork"]
            latest = forks[-1]["meta"].get("verdict") if forks else None
            if latest != "pass":
                _fail({"closed": False, "rule_ref": "adr:001",
                        "reason": f"slice {args.slice} resolves security-"
                                  f"marked decision rows {sec_rows} — an "
                                  f"independent forked review is required "
                                  f"before close (latest fork verdict: "
                                  f"{latest or 'none'}). Dispatch the "
                                  f"harness:reviewer agent with fresh "
                                  f"context; it records its verdict with "
                                  f"`harness review --record-fork pass "
                                  f"--slice {args.slice}`"})
            fork_review = "pass"

    # Precondition 1.6: the review stack RUNS here, over the slice's own
    # diff, and its verdict is recorded. Review used to be prompt discipline
    # — an agent could skip it and close green. Layer 0 + the deterministic
    # rubrics are engine-side; the agent's Layer 1-3 findings join via
    # `review --record-finding`, and both can block.
    review_result = {"ran": False, "verdict": None, "findings": []}
    if config.get("review", {}).get("run_at_close", True):
        from engine.graph import load_edges as _load_edges
        from engine.review import assemble, run_review
        diff_text = ""
        if args.commit and (root / ".git").exists():
            import subprocess
            base = sl.get("started_at_commit")
            rng = f"{base}..{args.commit}" if base else f"{args.commit}^!"
            dp = subprocess.run(["git", "-C", str(root), "diff", rng],
                                capture_output=True, text=True)
            diff_text = dp.stdout if dp.returncode == 0 else ""
        facts = assemble(root, diff_text, args.slice, config)
        result = run_review(root, facts, config, model=None)
        # findings the reviewer agent recorded for this slice count too
        recorded = [e for e in _load_edges(root)
                    if e["type"] == "reviewed_by"
                    and e["from"] == f"slice:{args.slice}"
                    and e.get("meta", {}).get("kind") == "finding"
                    and e.get("meta", {}).get("severity") == "block"]
        review_result = {"ran": True, "verdict": result["verdict"],
                         "findings": [f["code"] for f in result["findings"]],
                         "agent_blocking": [e["meta"]["code"] for e in recorded]}
        if result["verdict"] == "block" or recorded:
            _fail({"closed": False, "rule_ref": "review:layer1",
                    "reason": "review findings block this close — fix them "
                              "and re-close (agent-recorded blockers clear by "
                              "recording the fix, or by adjudication)",
                    "findings": result["findings"],
                    "agent_recorded": [e["meta"] for e in recorded]})
        from engine.graph import append_edge as _append_edge
        _append_edge(root, "reviewed_by", f"slice:{args.slice}", "review:close",
                     meta={"kind": "close", "verdict": result["verdict"],
                           "codes": sorted({f["code"] for f in result["findings"]})},
                     commit=args.commit)

    # Precondition 1.7: nothing parked for this slice may still be open —
    # a park is the reviewer saying a human must rule on it.
    from engine import read_jsonl as _read_jsonl
    open_parks = [p for p in _read_jsonl(harness_dir(root) / "parked.jsonl")
                  if p.get("slice") == args.slice]
    if open_parks:
        _fail({"closed": False, "rule_ref": "review:layer2",
                "reason": f"{len(open_parks)} finding(s) parked for "
                          f"{args.slice} await adjudication — run "
                          f"`harness adjudicate --list` and resolve them "
                          f"(every resolution writes substrate)",
                "parked": [p["finding"]["finding_id"] for p in open_parks]})

    # Precondition 2: unit_complete gate pack must not block.
    verdict = handle_event({
        "event": "unit_complete", "session_id": session,
        "work_unit_id": args.slice,
        "payload": {"files": [], "context_loaded": [], "diff": None, "prompt": None},
    }, root)
    if verdict["verdict"] == "block":
        _fail({"closed": False, "reason": "unit_complete gates block",
                "findings": verdict["findings"]})

    # Precondition 3: uses ⊆ declares reconciled.
    ud = uses_vs_declares(root, args.slice)
    unreconciled = ud["unresolved"]
    if unreconciled:
        _fail({"closed": False,
                "reason": f"uses not ⊆ declares: {unreconciled} (amend the "
                          f"slice declaration or record an override)"})

    sidecar = Sidecar(root)
    try:
        touched = sorted(sidecar.touched_paths(slice_id=args.slice))
    finally:
        sidecar.close()

    # W11: git is ground truth for what changed — hook-recorded touches are
    # an optimization that misses bash-side edits. Union the slice's diff
    # (bind commit .. close commit); substrate churn stays out of the set.
    if args.commit and sl.get("started_at_commit") and (root / ".git").exists():
        import subprocess
        dp = subprocess.run(["git", "-C", str(root), "diff", "--name-only",
                             f"{sl['started_at_commit']}..{args.commit}"],
                            capture_output=True, text=True)
        if dp.returncode == 0:
            from engine import IGNORED_DIRS

            def _enforceable(rel):
                # build artifacts and vendored trees are not slice scope:
                # a repo without a tidy .gitignore would otherwise get G3
                # blocks for __pycache__/node_modules churn
                parts = Path(rel).parts
                return (rel and not rel.startswith(".harness/")
                        and not any(p in IGNORED_DIRS for p in parts))
            touched = sorted(set(touched) |
                             {ln.strip() for ln in dp.stdout.splitlines()
                              if _enforceable(ln.strip())})
        else:
            print(f"warning: git diff for touch reconciliation failed: "
                  f"{dp.stderr.strip()}", file=sys.stderr)
    elif args.commit and (root / ".git").exists():
        # skipping the union silently is how worktree closes went vacuous —
        # loud, and the fix is named (S1)
        print(f"warning: slice {args.slice} has no started_at_commit — touch "
              f"reconciliation is limited to hook-recorded edits; re-bind "
              f"with `harness slice --slice {args.slice}` to record the "
              f"anchor for future slices", file=sys.stderr)

    # Precondition 4: G3 declaration reconciliation (T2: unit cannot close
    # until every touched file is declared/predicted or overridden).
    registry_sources = {e.get("source") for e in load_registry(root)
                        if e["id"] in sl.get("declares_dep", [])}
    declared = set(sl.get("predicted_files", [])) | registry_sources | \
        set(sl.get("acceptance", []))
    # overrides consult the same ledger as G3/G5: any recorded target
    # (file:path, boundary:B-x, registry:x) reconciles by bare id (#21)
    overridden = {e["to"].split(":", 1)[-1] for e in load_edges(root)
                  if e["from"] == f"slice:{args.slice}"
                  and e["type"] == "override"}
    rogue = [t for t in touched
             if not t.startswith(SUBSTRATE_PREFIXES)
             and t not in declared and t not in overridden]
    if rogue:
        _fail({"closed": False,
                "reason": f"G3 unreconciled: touched files not in the declared/"
                          f"predicted set: {rogue}; amend the slice declaration "
                          f"or record an override", "rule_ref": "gate:G3"})

    # Precondition 5 → the W3 ruling, now the documented contract: derived
    # artifacts are the ENGINE's job. A touched shadow-eligible file with no
    # shadow (the md-file-bug class) gets extracted HERE, deterministically,
    # and reported; the close only blocks if extraction itself fails. G7
    # still blocks anything stale or hand-edited.
    from engine import IGNORED_EXTS
    from engine.extractor.engine import extract_path, shadow_path_for
    shadows_extracted, shadow_failures = [], []
    for rel in sorted(touched):
        if rel.startswith(SUBSTRATE_PREFIXES):
            continue
        p = root / rel
        # extensionless files (Makefile, scripts) get degenerate shadows —
        # enforced surface too, not a loophole. Dotfiles (.gitignore,
        # .gitattributes…) are config, not modules.
        if (not p.is_file() or p.suffix.lower() in IGNORED_EXTS
                or p.name.startswith(".")):
            continue
        if shadow_path_for(root, p).exists():
            continue
        try:
            shadow, _sf = extract_path(root, p, config)
        except HarnessError as exc:
            shadow_failures.append({"path": rel, "reason": str(exc)})
            continue
        if shadow is None:
            shadow_failures.append({"path": rel, "reason": "not shadowable"})
        else:
            shadows_extracted.append(rel)
    if shadow_failures:
        _fail({"closed": False,
                "reason": f"touched files could not be shadowed: "
                          f"{shadow_failures} — fix the named cause and "
                          f"re-close", "rule_ref": "gate:G7"})

    # Precondition 6: a slice IS a commit boundary. Closing without one
    # records no provenance at all and used to succeed silently — the note
    # is the artifact that makes provenance travel with the repo.
    if (root / ".git").exists() and not args.commit:
        _fail({"closed": False, "rule_ref": "gate:G1",
                "reason": "--commit is required to close in a git repo: the "
                          "slice's provenance note is written onto it. "
                          "Commit the work and re-close with `--commit HEAD` "
                          "(the engine resolves the ref)."})

    # Precondition 7 (Y1): the named commit must actually CONTAIN the
    # touched files — `git add -N` (intent-to-add) produced a commit
    # without the slice's sources and the provenance note landed on the
    # wrong commit.
    if args.commit and (root / ".git").exists():
        import subprocess
        missing_from_commit = []
        for rel in sorted(touched):
            if rel.startswith(".harness/"):
                continue  # substrate commits separately by contract (W4)
            if not (root / rel).is_file():
                continue  # deletions are legitimately absent from the tree
            ok = subprocess.run(["git", "-C", str(root), "cat-file", "-e",
                                 f"{args.commit}:{rel}"], capture_output=True)
            if ok.returncode != 0:
                missing_from_commit.append(rel)
        if missing_from_commit:
            _fail({"closed": False, "rule_ref": "gate:G1",
                    "reason": f"commit {args.commit[:12]} does not contain "
                              f"touched files {missing_from_commit} — the "
                              f"provenance note would land on the wrong "
                              f"commit; `git add` them, commit, and re-close "
                              f"with the new HEAD"})

    # registry status flips (planned -> built) for modules this slice
    # produced; built entries whose source this slice touched (G6-acked
    # drift) get their recorded hash/digest refreshed, or verify would
    # report HASH_MISMATCH forever
    from engine.registry import refresh_built
    flipped, flip_skipped, refreshed = [], [], []
    for e in load_registry(root):
        in_scope = e.get("source") and (e["source"] in touched or
                                        e["source"] in sl.get("predicted_files", []))
        if not in_scope:
            continue
        try:
            if e.get("status") == "planned":
                flip_status(root, e["id"])
                flipped.append(e["id"])
                append_edge(root, "implements", f"slice:{args.slice}",
                            f"module:{e['id']}", commit=args.commit)
            elif e["source"] in touched:
                refresh_built(root, e["id"])
                refreshed.append(e["id"])
        except RegistryError as exc:
            # not silently: the entry keeps its status and the reason is named
            flip_skipped.append({"id": e["id"], "reason": str(exc)})

    # Precondition 8: dependency governance. Third-party deps are outside
    # shadow enforcement — a builder silently adding one is the drift class
    # G5 exists to stop, one level down. Added lines in dependency manifests
    # require a recorded override naming why.
    if args.commit and (root / ".git").exists():
        added = _added_dependency_lines(root, sl, args.commit)
        if added:
            from engine.graph import load_edges as _edges
            overridden_deps = {e["to"].split(":", 1)[-1]
                               for e in _edges(root)
                               if e["from"] == f"slice:{args.slice}"
                               and e["type"] == "override"
                               and e["to"].startswith("deps:")}
            rogue_deps = {f: lines for f, lines in added.items()
                          if f not in overridden_deps}
            if rogue_deps:
                _fail({"closed": False, "rule_ref": "gate:G5",
                        "reason": f"new dependencies added without a recorded "
                                  f"decision: {rogue_deps}. Record why: "
                                  f"`harness gates override --slice "
                                  f"{args.slice} --target deps:<file> "
                                  f"--rule-ref gate:G5 --justification "
                                  f'"<why>"` — or remove them.'})

    # git note: slice = commit boundary; provenance travels with the repo
    from engine.graph import NOTES_REF
    memory_ids = [m["id"] for m in memory.read_session(root, args.slice)]
    note_written, note_row = False, {}
    if args.commit:
        try:
            note_row = write_note(root, args.commit, {
                "slice_id": args.slice, "modules_touched": touched,
                "registry_used": sl.get("declares_dep", []),
                "memory_ids": memory_ids})
            note_written = True
        except GraphError as exc:
            # NOT a warning: an unwritten note means the provenance claim is
            # false for this slice. Block before any status mutation so the
            # close is retryable once the cause is fixed.
            _fail({"closed": False, "rule_ref": "gate:G1",
                    "reason": f"provenance note could not be written to "
                              f"{args.commit[:12]}: {exc}. Fix the cause "
                              f"(stale ref lock? read-only .git?) and "
                              f"re-close — provenance is not optional."})

    compacted = memory.compact_to_durable(root, args.slice, commit=args.commit)

    sl["status"] = "closed"
    save_slice(root, sl)

    # release every session binding pointing at the now-closed slice —
    # otherwise the next edit is gated against a closed slice (#22) — and
    # drop its G6 baselines so a later rebind starts fresh (S6)
    sidecar = Sidecar(root)
    try:
        released = sidecar.release_slice(args.slice)
        sidecar.release_snapshots(args.slice)
    finally:
        sidecar.close()

    telemetry.emit(root, "slice_closed", {"slice": args.slice,
                                          "flipped": flipped,
                                          "flip_skipped": flip_skipped,
                                          "memories": compacted["total"]})
    # hook-frequency events buffered in the sidecar land here, once, so the
    # tracked file doesn't churn on every edit (review R8)
    telemetry_flushed = telemetry.flush(root)
    telemetry_archived = telemetry.rotate(root, config)

    # The ceremony itself just mutated substrate (backlog flip, registry,
    # edges, telemetry) AFTER the commit it stamps — commit those mutations
    # or they ride as uncommitted worktree state and the flip is lost on
    # merge (parallel-worktree field report W4). A follow-up commit, never
    # an amend: amending args.commit would orphan its git note.
    # (Attempt-counter reset happens HERE, before the substrate commit —
    # resetting after it would dirty the sidecar post-commit.)
    _reset_close_attempts(root, args.slice)
    substrate_commit = None
    if args.commit and (root / ".git").exists():
        import subprocess

        def _git(*a):
            return subprocess.run(["git", "-C", str(root), *a],
                                  capture_output=True, text=True)
        if _git("status", "--porcelain", "--", ".harness").stdout.strip():
            _git("add", "-A", "--", ".harness")
            committed = _git("commit", "-q", "-m",
                             f"harness: close-slice {args.slice} substrate",
                             "--", ".harness")
            if committed.returncode == 0:
                substrate_commit = _git("rev-parse", "HEAD").stdout.strip()
            else:
                print(f"warning: substrate auto-commit failed: "
                      f"{committed.stderr.strip() or committed.stdout.strip()}",
                      file=sys.stderr)

    return {"closed": True, "slice": args.slice, "registry_flipped": flipped,
            "substrate_commit": substrate_commit,
            "shadows_extracted": shadows_extracted,
            "fork_review": fork_review,
            "review": review_result,
            "telemetry_flushed": telemetry_flushed,
            "telemetry_archived": telemetry_archived,
            "registry_refreshed": refreshed, "bindings_released": released,
            "flip_skipped": flip_skipped, "memory": compacted,
            "note_written": note_written,
            "note_tree_hash": note_row.get("tree_hash"),
            "notes_ref": NOTES_REF if note_written else None,
            "notes_hint": (f"view with: git notes --ref={NOTES_REF} show "
                           f"{args.commit}") if note_written else None,
            "touched": touched}
