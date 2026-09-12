"""`harness close-slice` and `merge-slice` — the end of a slice.

close-slice runs the ceremony and counts substantive failures toward the
auto-park cap; merge-slice is the mechanical tail after an in-worktree
close.
"""
from __future__ import annotations

import json
import sys

from engine import HarnessError, get_slice, load_config, save_slice
from engine.cli.acceptance import GATE_REASON, gate_finding
from engine.cli.ceremony import _close_ceremony
from engine.cli.common import (_CeremonyFail, _config_merge_drivers, _print,
                               _reset_close_attempts, _root, _session)
from engine.cli.landing import land_pr, landing_config, redact
from engine.cli.slice import _regression_suite


def _bump_close_attempts(root, slice_id, config, payload) -> bool:
    """Count substantive close failures in the sidecar; at the cap, PARK the
    slice (status + reason + telemetry) so an unattended loop stops burning
    attempts and a human knows exactly why. Returns True when parked."""
    from engine import telemetry
    from engine.events import Sidecar
    cap = int(config.get("run", {}).get("max_close_attempts", 3))
    sidecar = Sidecar(root)
    try:
        n = int(sidecar.state_get("__attempts__", slice_id) or 0) + 1
        sidecar.state_set("__attempts__", slice_id, n)
    finally:
        sidecar.close()
    if n < cap:
        payload["close_attempts"] = n
        return False
    sl = get_slice(root, slice_id)
    sl["status"] = "parked"
    sl["parked_reason"] = str(payload.get("reason", ""))[:300]
    save_slice(root, sl)
    telemetry.emit(root, "slice_parked", {"slice": slice_id, "attempts": n,
                                          "reason": sl["parked_reason"]})
    _reset_close_attempts(root, slice_id)
    payload["close_attempts"] = n
    return True


def cmd_close_slice(args):
    root = _root(args)
    config = load_config(root)
    landing = landing_config(config)      # fail loud on a bogus block first
    try:
        payload = _close_ceremony(args)
    except _CeremonyFail as fail:
        from engine.cli.closure_state import recover_closure
        recover_closure(root, args.slice)
        payload = fail.payload
        payload.setdefault("closed", False)
        if fail.attempt and _bump_close_attempts(root, args.slice, config,
                                                 payload):
            payload["parked"] = True
        _print(payload)
        return 1
    except (HarnessError, OSError):
        from engine.cli.closure_state import recover_closure
        recover_closure(root, args.slice)
        raise
    if landing["mode"] == "pr":
        # D-009: in pr mode the close IS the landing. The ceremony already
        # committed substrate and wrote the note, so a failed push or
        # pr_cmd never un-closes the slice — it is reported, loudly, with a
        # non-zero exit so the agent sees it and re-lands (`harness land`).
        sl = get_slice(root, args.slice)
        try:
            landed = land_pr(root, sl, config,
                             note_meta={"commit": args.commit,
                                        "tree_hash": payload.get("note_tree_hash")})
        except HarnessError as exc:
            # A usage error (wrong branch) must not swallow the close payload
            # — and must write NOTHING: committing a pending marker onto
            # whatever branch happens to be checked out is worse than the
            # error it records. Nothing was pushed, so nothing is pending.
            landed = {"landed": False, "pushed": False, "error": str(exc)}
        payload.update(landed)
        if not landed["landed"]:
            payload["next"] = (f"fix the cause, then re-land with `harness "
                               f"land --slice {args.slice}` (the slice is "
                               f"closed; do not re-run close-slice)")
            _print(payload)
            return 1
    _print(payload)
    return 0


# ------------------------------------------------------------------ merge-slice
def cmd_merge_slice(args):
    """imp-4: the mechanical tail after an in-worktree close, one command —
    merge the slice branch into the current (main) tree, regenerate and
    commit shadows from the merged sources, run the G4 safety net, remove
    the worktree and branch."""
    import subprocess
    from engine import telemetry
    root = _root(args)
    config = load_config(root)
    landing = landing_config(config)
    if landing["mode"] == "pr":
        # D-009: merging locally in pr mode is how a protected base branch
        # gets bypassed. The PR is the landing; say where it is.
        from engine.events import make_finding
        row = get_slice(root, args.slice)
        where = (row.get("pr_url")
                 or f"push slice/{args.slice} to {redact(landing['remote'])} "
                    f"and open a PR with `harness close-slice` (or `harness "
                    f"land --slice {args.slice}` if it already closed)")
        _print({"merged": False, "slice": args.slice, "findings": [make_finding(
            "LANDING_MODE_PR", "adr:002",
            f"landing.mode is 'pr': slice {args.slice} lands by pull request "
            f"against {landing['base']}, not by a local merge — {where}",
            severity="block", key=args.slice)]})
        return 1

    def _git(*a):
        return subprocess.run(["git", "-C", str(root), *a],
                              capture_output=True, text=True)

    if not (root / ".git").is_dir():
        print("error: run merge-slice from the MAIN tree (in a worktree "
              ".git is a file)", file=sys.stderr)
        return 2
    branch = f"slice/{args.slice}"
    if _git("rev-parse", "--verify", branch).returncode != 0:
        print(f"error: branch {branch!r} not found", file=sys.stderr)
        return 1

    # the slice must be CLOSED on its branch — merging in-progress work
    # smuggles unclosed state past every gate
    closed = False
    show = _git("show", f"{branch}:.harness/backlog.jsonl")
    if show.returncode == 0:
        for line in show.stdout.splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("id") == args.slice:
                closed = r.get("status") == "closed"
    if not closed:
        _print({"merged": False,
                "reason": f"slice {args.slice} is not closed on {branch} — "
                          f"run close-slice in the worktree first"})
        return 1

    # From this point rollback uses a hard reset, which is safe only when it
    # cannot erase the caller's tracked working-tree or index changes.
    # Untracked and ignored files (including the sidecar/session state) are
    # intentionally outside this preflight and are never cleaned by us.
    dirty = _git("status", "--porcelain", "--untracked-files=no")
    if dirty.returncode != 0:
        _print({"merged": False, "rolled_back": False,
                "reason": "cannot verify a clean tracked worktree and index "
                          f"before merge: {dirty.stderr.strip()}"})
        return 1
    if dirty.stdout.strip():
        _print({"merged": False, "rolled_back": False,
                "reason": "merge-slice requires a clean tracked worktree "
                          "and index so rollback cannot erase user changes",
                "dirty": dirty.stdout.splitlines()})
        return 1
    head = _git("rev-parse", "HEAD")
    if head.returncode != 0:
        print(f"error: cannot resolve current HEAD: {head.stderr.strip()}",
              file=sys.stderr)
        return 1
    original_head = head.stdout.strip()

    def rollback(reason, **extra):
        reset = _git("reset", "--hard", original_head)
        current = _git("rev-parse", "HEAD")
        rolled_back = (reset.returncode == 0 and current.returncode == 0
                       and current.stdout.strip() == original_head)
        payload = {"merged": False, "rolled_back": rolled_back,
                   "reason": reason}
        if not rolled_back:
            payload["rollback_detail"] = (
                reset.stderr or reset.stdout or current.stderr).strip()[-500:]
        payload.update(extra)
        _print(payload)
        return 1

    def reject_uncommitted_product_changes(stage, expected_head):
        """Rollback if a check changed tracked/index state outside substrate."""
        status = _git("status", "--porcelain", "--untracked-files=no", "--",
                      ".", ":(exclude).harness",
                      ":(exclude).harness/**")
        current = _git("rev-parse", "HEAD")
        if status.returncode != 0 or current.returncode != 0:
            detail = (status.stderr or current.stderr or status.stdout).strip()
            return rollback(
                f"cannot verify tracked source after {stage} — merge rolled "
                f"back: {detail}")
        dirty_paths = status.stdout.splitlines()
        if dirty_paths or current.stdout.strip() != expected_head:
            return rollback(
                f"{stage} changed tracked source or index state after merge; "
                "only committed slice bytes may land",
                dirty=dirty_paths,
                expected_head=expected_head,
                observed_head=current.stdout.strip())
        return None

    _config_merge_drivers(root)   # S8: drivers before any merge, always
    merged = _git("merge", "--no-edit", branch)
    if merged.returncode != 0:
        unmerged = _git("diff", "--name-only", "--diff-filter=U").stdout.split()
        if not unmerged:
            # Y3: transient 'strategy ort failed' with zero conflicts —
            # one loud retry
            print("warning: merge failed with no conflicted paths; "
                  "retrying once (Y3)", file=sys.stderr)
            merged = _git("merge", "--no-edit", branch)
        if merged.returncode != 0:
            # NEVER leave main mid-merge: conflict markers inside
            # .harness/*.jsonl are substrate corruption. Abort, report, and
            # name the likely cause.
            unmerged = _git("diff", "--name-only",
                            "--diff-filter=U").stdout.split()
            return rollback(
                "slice merge failed and was rolled back",
                conflicts=unmerged or None,
                detail=(merged.stderr or merged.stdout).strip()[-500:],
                hint="keyed substrate conflicts resolve mechanically when "
                     "the merge drivers are installed — if .gitattributes "
                     "lacks the harness entries, run `harness init --migrate`")

    merged_head_result = _git("rev-parse", "HEAD")
    if merged_head_result.returncode != 0:
        return rollback(
            "cannot resolve the merged revision — merge rolled back: "
            f"{merged_head_result.stderr.strip()}")
    merged_head = merged_head_result.stdout.strip()

    # the merged tree is what ships: the FULL accumulated acceptance suite
    # must be green on it. Each side being green alone proves nothing about
    # the combination — on red, the merge is rolled back, loudly, and the
    # branch/worktree stay put for fixing.
    try:
        config = load_config(root)
        ok, detail = _regression_suite(root, config)
        gate, gate_tail = gate_finding(root, config) if ok else (None, "")
    except Exception as exc:
        return rollback(f"merged-tree acceptance checks failed: {exc}")
    if not ok or gate is not None:
        payload = {}
        reason = (f"merged tree fails the accumulated acceptance suite — "
                  f"merge rolled back; fix on branch {branch} and re-run "
                  f"merge-slice.\n{detail}" if not ok else GATE_REASON)
        if gate is not None:
            payload["rule_ref"] = gate["rule_ref"]
            payload["evidence"] = gate_tail
            payload["findings"] = [gate]
        return rollback(reason, **payload)
    changed = reject_uncommitted_product_changes(
        "merged-tree acceptance checks", merged_head)
    if changed is not None:
        return changed

    # shadows never content-merge (W10): regenerate from the merged tree,
    # THEN run the G4 safety net, THEN commit — every byte this ceremony
    # writes (shadows, telemetry) rides in its own substrate commit
    from engine.extractor.engine import extract_all
    try:
        ex = extract_all(root, config)
    except Exception as exc:
        return rollback(
            f"merged-tree extraction failed — merge rolled back: {exc}")
    changed = reject_uncommitted_product_changes(
        "merged-tree extraction", merged_head)
    if changed is not None:
        return changed

    from engine.events import handle_event
    try:
        verdict = handle_event({
            "event": "unit_complete", "session_id": _session(args, root),
            "work_unit_id": args.slice,
            "payload": {"files": [], "context_loaded": [], "diff": None,
                        "prompt": None}}, root)
    except Exception as exc:
        return rollback(
            f"merged-tree event checks failed — merge rolled back: {exc}")
    if verdict["verdict"] == "block":
        return rollback(
            "merged tree failed unit_complete gates — merge rolled back; "
            f"fix on branch {branch} and re-run merge-slice",
            gates="block", findings=verdict["findings"],
            shadows={"written": len(ex["written"]),
                     "pruned": ex["pruned"]})
    changed = reject_uncommitted_product_changes(
        "merged-tree event checks", merged_head)
    if changed is not None:
        return changed
    telemetry.emit(root, "slice_merged", {
        "slice": args.slice, "gates": verdict["verdict"],
        "shadows_written": len(ex["written"]), "pruned": ex["pruned"]})
    telemetry.flush(root)      # buffered hook events land with the merge
    changed = reject_uncommitted_product_changes(
        "merge telemetry", merged_head)
    if changed is not None:
        return changed

    substrate_commit = None
    if _git("status", "--porcelain", "--", ".harness").stdout.strip():
        added = _git("add", "-A", "--", ".harness")
        if added.returncode != 0:
            return rollback(
                "substrate regeneration could not be staged — merge rolled "
                f"back: {added.stderr.strip() or added.stdout.strip()}",
                gates=verdict["verdict"],
                findings=[f["code"] for f in verdict["findings"]],
                substrate_commit=None)
        c = _git("commit", "-q", "-m",
                 f"harness: merge-slice {args.slice} substrate regen",
                 "--", ".harness")
        if c.returncode == 0:
            substrate_commit = _git("rev-parse", "HEAD").stdout.strip()
        else:
            return rollback(
                "substrate regeneration commit failed — merge rolled back: "
                f"{c.stderr.strip() or c.stdout.strip()}",
                gates=verdict["verdict"],
                findings=[f["code"] for f in verdict["findings"]],
                substrate_commit=None)

    expected_final_head = substrate_commit or merged_head
    changed = reject_uncommitted_product_changes(
        "substrate finalization", expected_final_head)
    if changed is not None:
        return changed

    cleanup = {"worktree_removed": False, "branch_deleted": False}
    wt = root / ".worktrees" / args.slice
    if wt.exists():
        # --force: the gitignored sidecar makes every worktree "dirty"
        r = _git("worktree", "remove", "--force", str(wt))
        cleanup["worktree_removed"] = r.returncode == 0
        if r.returncode != 0:
            print(f"warning: worktree not removed: {r.stderr.strip()}",
                  file=sys.stderr)
    r = _git("branch", "-d", branch)
    cleanup["branch_deleted"] = r.returncode == 0

    _print({"merged": True, "slice": args.slice,
            "gates": verdict["verdict"],
            "findings": [f["code"] for f in verdict["findings"]],
            "shadows": {"written": len(ex["written"]),
                        "pruned": ex["pruned"]},
            "substrate_commit": substrate_commit, **cleanup})
    return 0
