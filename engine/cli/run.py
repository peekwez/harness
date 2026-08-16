"""`harness run` — the campaign dispatcher.

Walks the dependency DAG, provisions each ready slice, invokes the host's
configured builder agent, merges closes and parks failures.
"""
from __future__ import annotations

import json
import os
import sys

from engine import get_slice, load_backlog, load_config, save_slice
from engine.cli.common import PLUGIN_ROOT, _print, _root


# ------------------------------------------------------------------ run
def cmd_run(args):
    """The campaign dispatcher: walk the dependency DAG, provision each
    ready slice (worktree + sandbox + binding), invoke the configured
    builder agent, merge closes, park failures, repeat until the backlog is
    empty or something needs a human. The engine orchestrates and enforces;
    the AGENT is the host's (`run.builder_cmd`) — that boundary is the
    portability contract, not a shortcut: point it at `claude -p`, an Agent
    SDK script, or any CLI that can drive the slice loop.

    Exit 0: backlog fully closed and merged. Exit 2: stopped on a park (the
    report names it). Exit 1: dispatcher error."""
    import shlex
    import subprocess
    import time
    from engine import telemetry
    root = _root(args)
    config = load_config(root)
    run_cfg = config.get("run") or {}
    harness_bin = str(PLUGIN_ROOT / "bin" / "harness")

    if not (root / ".git").is_dir():
        print("error: run dispatches worktrees — it needs the MAIN tree of "
              "a git repo", file=sys.stderr)
        return 2

    def statuses():
        return {s["id"]: s for s in load_backlog(root)}

    def ready(rows):
        return sorted(sid for sid, s in rows.items()
                      if s.get("status") == "planned"
                      and all(rows.get(d, {}).get("status") == "closed"
                              for d in s.get("depends_on", []) or []))

    if args.dry_run:
        rows = statuses()
        waves, closed = [], {sid for sid, s in rows.items()
                             if s.get("status") == "closed"}
        pending = {sid for sid, s in rows.items()
                   if s.get("status") == "planned"}
        while pending:
            wave = sorted(sid for sid in pending
                          if all(d in closed for d in
                                 rows[sid].get("depends_on", []) or []))
            if not wave:
                break  # blocked (parked dep or cycle) — reported below
            waves.append(wave)
            closed |= set(wave)
            pending -= set(wave)
        _print({"waves": waves, "blocked": sorted(pending),
                "lanes": int(args.lanes)})
        return 0

    builder_cmd = args.builder_cmd or run_cfg.get("builder_cmd")
    if not builder_cmd:
        print("error: no builder configured — set run.builder_cmd in "
              ".harness/config.yaml (e.g. a `claude -p` invocation or any "
              "agent CLI that drives the slice loop) or pass --builder-cmd",
              file=sys.stderr)
        return 2
    lanes = max(1, int(args.lanes))
    max_attempts = int(run_cfg.get("max_slice_attempts", 2))
    timeout = int(run_cfg.get("builder_timeout", 3600))

    def hcli(*a):
        return subprocess.run([sys.executable, harness_bin,
                               "--root", str(root), *a],
                              capture_output=True, text=True)

    def park(sid, reason):
        sl = get_slice(root, sid)
        sl["status"] = "parked"
        sl["parked_reason"] = reason[:300]
        save_slice(root, sl)
        telemetry.emit(root, "slice_parked", {"slice": sid, "reason": reason[:300]})
        # commit the park immediately: dirty main substrate would block
        # every later lane's merge (the W4 principle, dispatcher edition)
        subprocess.run(["git", "-C", str(root), "add", "-A", "--", ".harness"],
                       capture_output=True)
        c = subprocess.run(["git", "-C", str(root), "commit", "-q", "-m",
                            f"harness: park {sid}", "--", ".harness"],
                           capture_output=True, text=True)
        if c.returncode != 0:
            print(f"warning: park commit failed: {c.stderr.strip()}",
                  file=sys.stderr)

    completed, attempts, active = [], {}, {}
    while True:
        rows = statuses()
        parked_now = sorted(sid for sid, s in rows.items()
                            if s.get("status") == "parked")
        if parked_now and not active:
            break  # stop loudly: a human owns parked slices
        wave = ready(rows)
        # launch builders up to the lane cap
        for sid in wave:
            if len(active) >= lanes or sid in active:
                continue
            start = hcli("start", "--slice", sid, "--session", f"run:{sid}")
            if start.returncode != 0:
                park(sid, f"start failed: "
                          f"{(start.stdout or start.stderr).strip()[:200]}")
                continue
            wt = json.loads(start.stdout).get("worktree") or str(root)
            env = dict(os.environ)
            env.update({"HARNESS_BIN": harness_bin, "HARNESS_SLICE": sid,
                        "HARNESS_WORKTREE": wt, "HARNESS_ROOT": str(root),
                        "CLAUDE_SESSION_ID": f"run:{sid}"})
            print(f"run: dispatching builder for {sid} in {wt}",
                  file=sys.stderr)
            active[sid] = {"proc": subprocess.Popen(
                builder_cmd, shell=True, cwd=wt, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True),
                "worktree": wt, "deadline": time.monotonic() + timeout}
        if not active:
            planned = [sid for sid, s in rows.items()
                       if s.get("status") in ("planned", "in_progress")]
            if planned and not parked_now:
                park(planned[0], "unreachable: dependencies can never close "
                                 "(cycle or parked dependency)")
                continue
            break  # nothing running, nothing launchable: campaign over
        # wait for any builder to finish (merges serialize below)
        finished = None
        while finished is None:
            for sid, lane in list(active.items()):
                if lane["proc"].poll() is not None:
                    finished = sid
                    break
                if time.monotonic() > lane["deadline"]:
                    lane["proc"].kill()
                    finished = sid
                    break
            if finished is None:
                time.sleep(0.2)
        lane = active.pop(finished)
        tail = (lane["proc"].stdout.read() or "").strip()[-400:]
        # did the builder actually CLOSE the slice on its branch?
        show = subprocess.run(
            ["git", "-C", str(root), "show",
             f"slice/{finished}:.harness/backlog.jsonl"],
            capture_output=True, text=True)
        closed_on_branch = any(
            r.get("id") == finished and r.get("status") == "closed"
            for r in (json.loads(ln) for ln in show.stdout.splitlines()
                      if ln.strip())) if show.returncode == 0 else False
        if closed_on_branch:
            merged = hcli("merge-slice", "--slice", finished,
                          "--session", f"run:{finished}")
            if merged.returncode == 0:
                completed.append(finished)
                telemetry.emit(root, "slice_dispatched", {"slice": finished})
                continue
            failure = f"merge failed: {(merged.stdout or '').strip()[-300:]}"
        else:
            failure = (f"builder exited rc={lane['proc'].returncode} without "
                       f"closing the slice; tail: {tail}")
        attempts[finished] = attempts.get(finished, 0) + 1
        if attempts[finished] >= max_attempts:
            park(finished, f"{attempts[finished]} attempts: {failure}")
        else:
            print(f"run: retrying {finished} "
                  f"({attempts[finished]}/{max_attempts}): {failure[:160]}",
                  file=sys.stderr)

    rows = statuses()
    parked = sorted(sid for sid, s in rows.items()
                    if s.get("status") == "parked")
    payload = {
        "completed": completed, "parked": parked,
        "remaining": sorted(sid for sid, s in rows.items()
                            if s.get("status") not in ("closed",)),
        "next": (None if not parked else
                 "a human owns parked slices: `harness adjudicate --list` "
                 "for review parks, or re-bind to unpark and retry "
                 "(`harness slice --slice <id>`); worktrees are kept for "
                 "inspection"),
    }
    _print(payload)
    return 0 if not parked and not payload["remaining"] else 2
