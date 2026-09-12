"""Slice binding and its preconditions: start, permit, acceptance runs.

`_bind_slice` is everything binding a slice entails (shared by `slice` and
`start`); the acceptance/regression runners are the engine-side gates that
`close-slice` and `merge-slice` call.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from engine import (HarnessError, get_slice, load_backlog, load_config,
                    save_slice)
from engine.cli.acceptance import run_acceptance, run_regression
from engine.cli.common import (PLUGIN_ROOT, _acceptance_python,
                               _config_merge_drivers, _print, _root, _session)
from engine.cli.init import _write_autonomy_settings


SLICE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _slice_id_refusal(slice_id: str):
    if not isinstance(slice_id, str) or not SLICE_ID.fullmatch(slice_id):
        return {"bound": False, "reason":
                f"slice id {slice_id!r} must be one logical identifier "
                "containing only letters, digits, '.', '_' or '-'",
                "_exit_code": 2}
    return None


def _binding_refusal(root, sl, *, force=False, justification=None):
    malformed = _slice_id_refusal(sl.get("id"))
    if malformed:
        return malformed
    reason = (justification or "").strip()
    if force and not reason:
        return {"bound": False, "reason":
                "--force requires a nonwhitespace --justification (an "
                "override without a recorded reason is a silent bypass)",
                "_exit_code": 2}
    status = sl.get("status")
    if status == "closed":
        return {"bound": False, "reason":
                f"slice {sl['id']} is closed and cannot be bound for more "
                "writes", "rule_ref": "lifecycle:closed", "_exit_code": 1}
    if status not in ("planned", "in_progress", "parked"):
        return {"bound": False, "reason":
                f"slice {sl['id']} has unsupported lifecycle status "
                f"{status!r}", "rule_ref": "lifecycle:status",
                "_exit_code": 1}
    known = {s["id"]: s for s in load_backlog(root)}
    blocking = []
    for dep in sl.get("depends_on", []) or []:
        row = known.get(dep)
        if row is None:
            blocking.append(f"{dep} (not in the backlog)")
        elif row.get("status") != "closed":
            blocking.append(f"{dep} ({row.get('status')})")
    if blocking and not force:
        return {"bound": False, "started": False, "rule_ref": "gate:G1",
                "reason": f"slice {sl['id']} depends on unclosed slices: "
                          f"{blocking}. Close them first, or override with "
                          "`--force --justification \"<why>\"` (recorded).",
                "_exit_code": 1}
    return None


def _public_bind_result(result):
    result = dict(result)
    return result.pop("_exit_code", 0), result


def _bind_slice(root, slice_id: str, session: str, *, force=False,
                justification=None) -> dict:
    """Everything binding a slice entails, in one place (shared by `slice`
    and `start`): session + repo-default binding, declares_dep edges, status
    flip, git anchor, G6 baseline, context registration, merge drivers."""
    from engine.events import Sidecar, _snapshot_slice_baseline
    from engine.graph import append_edge, load_edges
    from engine.resolver import resolve as _resolve
    malformed = _slice_id_refusal(slice_id)
    if malformed:
        return malformed
    sl = get_slice(root, slice_id)
    refusal = _binding_refusal(root, sl, force=force,
                               justification=justification)
    if refusal:
        return refusal
    justification = (justification or "").strip()

    existing_edges = load_edges(root)
    existing = {(e["type"], e["from"], e["to"]) for e in existing_edges}
    if force:
        for dep in sl.get("depends_on", []) or []:
            row = next((s for s in load_backlog(root)
                        if s.get("id") == dep), None)
            if row is not None and row.get("status") == "closed":
                continue
            already_recorded = any(
                e["type"] == "override"
                and e["from"] == f"slice:{slice_id}"
                and e["to"] == f"slice:{dep}"
                and e.get("meta", {}).get("rule_ref") == "gate:G1"
                and e.get("meta", {}).get("kind") == "dependency_order"
                for e in existing_edges)
            if not already_recorded:
                append_edge(root, "override", f"slice:{slice_id}",
                            f"slice:{dep}",
                            meta={"rule_ref": "gate:G1",
                                  "kind": "dependency_order",
                                  "justification": justification})
                existing.add(("override", f"slice:{slice_id}",
                              f"slice:{dep}"))
    sidecar = Sidecar(root)
    try:
        # Bind for the named session AND as the repo default: hook events
        # carry the host's real session UUID, which nobody can pass to a CLI
        # in advance (field report #18) — the default is what gates fall
        # back to when the hook's session has no explicit binding.
        sidecar.state_set(session, "active_slice", slice_id)
        sidecar.state_set("__default__", "active_slice", slice_id)
    finally:
        sidecar.close()
    for dep in sl.get("declares_dep", []):
        key = ("declares_dep", f"slice:{slice_id}", f"module:{dep}")
        if key not in existing:
            append_edge(root, *key)
    dirty = False
    if sl.get("status") in ("planned", "parked"):
        # binding a PARKED slice is the human's deliberate unpark
        sl["status"] = "in_progress"
        sl.pop("parked_reason", None)
        dirty = True
    # record where the slice started: close-slice diffs from here to catch
    # edits the hooks never saw (W11). Backfilled on ANY bind regardless of
    # status: a worktree checkout carries the committed row without the
    # anchor, and re-binding there must repair it (S1).
    if (root / ".git").exists() and not sl.get("started_at_commit"):
        import subprocess
        rp = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                            capture_output=True, text=True)
        if rp.returncode == 0:
            sl["started_at_commit"] = rp.stdout.strip()
            dirty = True
    if dirty:
        save_slice(root, sl)

    # G6 baseline at bind: Phase-1 hook events may never route to this
    # substrate (worktree sessions), so binding is the reliable slice-start
    # moment (S1). INSERT OR IGNORE keeps the earliest baseline on re-bind.
    # The resolved context is registered for this session ONLY because the
    # caller emits the injections it names — G2 must never certify context
    # nobody printed (review finding R3).
    res = _resolve(root, slice_id, load_config(root))
    sidecar = Sidecar(root)
    try:
        _snapshot_slice_baseline(root, sidecar, slice_id)
        sidecar.context_add(session, res["context_loaded"],
                            injections=res["injections"])
    finally:
        sidecar.close()

    # merge drivers live in repo-local git config, which does not travel
    # with clones (S8) — re-assert the CONFIG half at every bind (idempotent
    # and tree-untouching) so drivers exist before any merge on this machine
    _config_merge_drivers(root)

    return {"bound": True, "active_slice": slice_id, "session": session,
            "status": sl["status"],
            "context_registered": len(res["context_loaded"]),
            "context_loaded": res["context_loaded"],
            "injections": res["injections"],
            "acceptance_python": _acceptance_python(root, load_config(root)),
            "started_at_commit": sl.get("started_at_commit")}


def _acceptance_green(root, sl, config):
    """§7.5 precondition, engine-enforced: gates live in CLI, not in prompts.

    Kept as the ceremony's entry point; the runner itself (D-012) lives in
    `engine.cli.acceptance`.
    """
    return run_acceptance(root, sl, config)


def _regression_suite(root, config, exclude=None, interpreter=None, env=None):
    """(ok, detail): run every CLOSED slice's acceptance paths. Shared by
    close (pre-close, in the slice tree) and merge-slice (post-merge, with
    rollback)."""
    return run_regression(root, config, exclude=exclude,
                          interpreter=interpreter, env=env)


# ------------------------------------------------------------------ start
def cmd_start(args):
    """One command to begin a slice: isolated worktree, provisioned sandbox
    + autonomy profile, bound slice, Phase-1 context emitted. Nothing here
    asks a human anything — that is the whole point."""
    import subprocess
    from engine.cli.landing import landing_config
    root = _root(args)
    malformed = _slice_id_refusal(args.slice)
    if malformed:
        _, public = _public_bind_result(malformed)
        print(public["reason"], file=sys.stderr)
        return 2
    sl = get_slice(root, args.slice)     # fail loud before touching git

    # Validate the transition before creating a filesystem path.  The same
    # check runs again inside _bind_slice in the target tree, where it is the
    # authoritative guard for every binding caller.
    refusal = _binding_refusal(root, sl, force=args.force,
                               justification=args.justification)
    if refusal:
        code, public = _public_bind_result(refusal)
        if code == 2:
            print(public["reason"], file=sys.stderr)
        else:
            _print(public)
        return code

    # pr landing pushes the slice's OWN branch from the slice's own tree
    # (D-009): binding in the main tree would leave the close with nothing
    # to push, or push whatever `slice/<id>` happens to point at.
    if args.no_worktree and landing_config(load_config(root))["mode"] == "pr":
        raise HarnessError(
            "landing.mode: pr requires the slice worktree — the close pushes "
            "slice/" + str(args.slice) + " from it. Drop --no-worktree, or "
            "set landing.mode: local in .harness/config.yaml")

    resumed, worktree, branch = False, None, None

    if not args.no_worktree:
        if not (root / ".git").exists():
            print("error: --no-worktree is required outside a git repo",
                  file=sys.stderr)
            return 1
        branch = f"slice/{args.slice}"
        worktree = root / ".worktrees" / args.slice

        def _git(*a):
            return subprocess.run(["git", "-C", str(root), *a],
                                  capture_output=True, text=True)
        if worktree.exists():
            resumed = True
        else:
            worktree.parent.mkdir(parents=True, exist_ok=True)
            have_branch = _git("rev-parse", "--verify", branch).returncode == 0
            cmd = (["worktree", "add", str(worktree), branch] if have_branch
                   else ["worktree", "add", str(worktree), "-b", branch])
            r = _git(*cmd)
            if r.returncode != 0:
                print(f"error: worktree add failed: {r.stderr.strip()}",
                      file=sys.stderr)
                return 1
            resumed = have_branch

    target = worktree or root
    settings_written = _write_autonomy_settings(target, quiet=True,
                                                 local=worktree is not None)
    bound = _bind_slice(target, args.slice, _session(args, target),
                        force=args.force, justification=args.justification)
    code, bound = _public_bind_result(bound)
    if code:
        _print(bound)
        return code

    _print({**bound, "slice": args.slice, "resumed": resumed,
            "worktree": str(worktree) if worktree else None,
            "branch": branch, "settings_written": settings_written,
            "next": (f"work the red acceptance tests, then "
                     f"`harness close-slice --slice {args.slice} --commit HEAD`"
                     f" from {target}")})
    return 0


# ------------------------------------------------------------------ permit
def cmd_permit(args):
    """Host permission query — NOT an EnforcementEvent. Answers "would the
    harness approve this?" so a bound slice never stops for a prompt. Only
    ever returns allow=true; a false is "not auto-approved", leaving the
    host's normal flow (and the human) in charge."""
    from engine.events import Sidecar
    from engine.permits import command_decision, paths_in_scope
    from engine.registry import load_registry
    root = _root(args)
    session = _session(args, root)
    sidecar = Sidecar(root)
    try:
        slice_id = (args.slice or sidecar.state_get(session, "active_slice")
                    or sidecar.state_get("__default__", "active_slice"))
    finally:
        sidecar.close()
    if not slice_id:
        _print({"allow": False, "reason": "no slice bound to this session — "
                                          "auto-approval is scoped to a bound slice"})
        return 0
    if args.command:
        # the bound slice and the repo's landing block are both part of the
        # answer now: pr-mode egress is scoped to THIS slice's branch, and a
        # refusal there is a DENY the adapter must emit, not silence (D-011)
        decision, allow, reason = command_decision(
            args.command, harness_bin=str(PLUGIN_ROOT / "bin" / "harness"),
            config=load_config(root), slice_id=slice_id)
        _print({"allow": allow, "decision": decision, "reason": reason,
                "slice": slice_id})
        return 0
    if args.paths:
        rels = []
        for p in args.paths:
            pp = Path(p)
            if pp.is_absolute():
                try:
                    pp = pp.resolve().relative_to(Path(root).resolve())
                except ValueError:
                    _print({"allow": False, "reason": f"{p} is outside the repo",
                            "slice": slice_id})
                    return 0
            rels.append(str(pp))
        sl = get_slice(root, slice_id)
        ok = paths_in_scope(sl, load_registry(root), rels)
        _print({"allow": ok, "decision": "allow" if ok else "defer",
                "slice": slice_id,
                "reason": (f"gate-approved for slice {slice_id} (declared "
                           f"scope)" if ok else
                           "outside the slice's declared/predicted set — "
                           "amend the declaration to work here")})
        return 0
    print("error: pass --command or --paths", file=sys.stderr)
    return 2
