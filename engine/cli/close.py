"""`harness close-slice` and `merge-slice` — the end of a slice.

close-slice runs the ceremony and counts substantive failures toward the
auto-park cap; merge-slice is the mechanical tail after an in-worktree
close.
"""
from __future__ import annotations

import json
import sys

from engine import get_slice, load_config, save_slice
from engine.cli.acceptance import GATE_REASON, gate_finding
from engine.cli.ceremony import _close_ceremony
from engine.cli.common import (_CeremonyFail, _config_merge_drivers, _print,
                               _reset_close_attempts, _root, _session)
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
    try:
        payload = _close_ceremony(args)
    except _CeremonyFail as fail:
        payload = fail.payload
        payload.setdefault("closed", False)
        if fail.attempt and _bump_close_attempts(root, args.slice, config,
                                                 payload):
            payload["parked"] = True
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
            _git("merge", "--abort")
            _print({"merged": False, "conflicts": unmerged or None,
                    "rolled_back": True,
                    "detail": (merged.stderr or merged.stdout).strip()[-500:],
                    "hint": "keyed substrate conflicts resolve mechanically "
                            "when the merge drivers are installed — if "
                            ".gitattributes lacks the harness entries, run "
                            "`harness init --migrate`"})
            return 1

    # the merged tree is what ships: the FULL accumulated acceptance suite
    # must be green on it. Each side being green alone proves nothing about
    # the combination — on red, the merge is rolled back, loudly, and the
    # branch/worktree stay put for fixing.
    ok, detail = _regression_suite(root, config)
    # the gate runs on the MERGED tree but with the config as it stands in
    # this (pre-merge) tree — a slice that introduces `gate_cmd` on its own
    # branch is honoured from the next merge on
    gate, gate_tail = gate_finding(root, config) if ok else (None, "")
    if not ok or gate is not None:
        rolled = _git("reset", "--hard", "ORIG_HEAD")
        payload = {"merged": False, "rolled_back": rolled.returncode == 0,
                   "reason": (f"merged tree fails the accumulated acceptance "
                              f"suite — merge rolled back; fix on branch "
                              f"{branch} and re-run merge-slice.\n{detail}")
                             if not ok else GATE_REASON}
        if gate is not None:
            payload["rule_ref"] = gate["rule_ref"]
            payload["evidence"] = gate_tail
            payload["findings"] = [gate]
        _print(payload)
        return 1

    # shadows never content-merge (W10): regenerate from the merged tree,
    # THEN run the G4 safety net, THEN commit — every byte this ceremony
    # writes (shadows, telemetry) rides in its own substrate commit
    from engine.extractor.engine import extract_all
    ex = extract_all(root, config)

    from engine.events import handle_event
    verdict = handle_event({
        "event": "unit_complete", "session_id": _session(args, root),
        "work_unit_id": args.slice,
        "payload": {"files": [], "context_loaded": [], "diff": None,
                    "prompt": None}}, root)
    telemetry.emit(root, "slice_merged", {
        "slice": args.slice, "gates": verdict["verdict"],
        "shadows_written": len(ex["written"]), "pruned": ex["pruned"]})
    telemetry.flush(root)      # buffered hook events land with the merge

    substrate_commit = None
    if _git("status", "--porcelain", "--", ".harness").stdout.strip():
        _git("add", "-A", "--", ".harness")
        c = _git("commit", "-q", "-m",
                 f"harness: merge-slice {args.slice} substrate regen",
                 "--", ".harness")
        if c.returncode == 0:
            substrate_commit = _git("rev-parse", "HEAD").stdout.strip()
        else:
            print(f"warning: substrate regen commit failed: "
                  f"{c.stderr.strip() or c.stdout.strip()}", file=sys.stderr)

    cleanup = {"worktree_removed": False, "branch_deleted": False}
    if verdict["verdict"] != "block":
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
    return 0 if verdict["verdict"] != "block" else 1
