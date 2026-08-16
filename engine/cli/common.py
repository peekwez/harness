"""Shared CLI helpers used by more than one command family.

The plugin root (merge drivers and autonomy profiles point at it), substrate
root and session resolution, JSON output, the acceptance interpreter, the
git merge-driver installers, and the close ceremony's failure/attempt
primitives.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from engine import find_root

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent


def _root(args):
    if getattr(args, "root", None):
        return Path(args.root).resolve()
    return find_root()


def _print(obj):
    print(json.dumps(obj, sort_keys=True, indent=2))


def _main_worktree_root(root):
    """If `root` is a linked git worktree, return the MAIN worktree root; else
    None. A worktree has its own fresh .harness/sidecar.db, so the live host
    session the hooks recorded lives in the MAIN repo's sidecar, not the
    worktree's (field report Y2)."""
    import subprocess
    r = subprocess.run(["git", "-C", str(root), "rev-parse",
                        "--path-format=absolute", "--git-common-dir"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    common = Path(r.stdout.strip())          # main repo's .git dir
    if common.name == ".git" and common.parent != Path(root).resolve():
        return common.parent
    return None


def _session(args, root=None):
    """--session > $CLAUDE_SESSION_ID > the live hook session recorded in
    the sidecar > "cli". Builder shells often lack the env export (Y2); the
    sidecar fallback joins the session the hooks are actually gating
    instead of creating a parallel 'cli' one. In a worktree the hooks write
    the live session into the MAIN repo's sidecar, so consult that too."""
    s = (getattr(args, "session", None)
         or os.environ.get("CLAUDE_SESSION_ID"))
    if s:
        return s
    if root is not None:
        from engine.events import Sidecar
        roots = [root]
        main = _main_worktree_root(root)
        if main is not None:
            roots.append(main)
        for r in roots:
            sidecar = Sidecar(r)
            try:
                s = sidecar.state_get("__hooks__", "last_session_id")
            finally:
                sidecar.close()
            if s:
                return s
    return s or "cli"


# ------------------------------------------------------------------ doctor
def _dep_status():
    deps = {}
    for mod, pkg in (("yaml", "pyyaml"), ("tree_sitter", "tree-sitter"),
                     ("tree_sitter_language_pack", "tree-sitter-language-pack")):
        try:
            __import__(mod)
            deps[pkg] = "ok"
        except ImportError:
            deps[pkg] = "MISSING"
    return deps


def _acceptance_python(root, config):
    """The interpreter that runs acceptance tests: explicit config wins,
    then the project's own venv, then the engine's interpreter. Running the
    engine's pyenv against a venv-pinned project fails on imports the
    project legitimately has (field report #20)."""
    configured = config["gates"].get("acceptance_python")
    if configured:
        p = Path(configured)
        if not p.is_absolute():
            p = Path(root) / p
        return str(p)
    for candidate in (".venv/bin/python", ".venv/Scripts/python.exe",
                      "venv/bin/python"):
        p = Path(root) / candidate
        if p.exists():
            return str(p)
    return sys.executable


# Parallel worktree closes conflict on .harness JSONL by construction (W5).
# Append-only logs union-merge; keyed-by-id rows go through the
# `harness merge-substrate` 3-way driver.
SUBSTRATE_UNION_MERGE = (".harness/telemetry.jsonl", ".harness/edges.jsonl",
                         ".harness/notes.jsonl",
                         ".harness/memory/durable.jsonl")


SUBSTRATE_KEYED_MERGE = (".harness/backlog.jsonl", ".harness/registry.jsonl",
                         ".harness/decisions.jsonl")


# Shadows are derived: content-merging them is semantically meaningless
# (W10). Keep ours, then regenerate from the merged sources — extract --all
# actually rewrites stale ones now that the cache is version-aware (W7).
SUBSTRATE_OURS_MERGE = (".harness/shadows/**",)


def _write_merge_attributes(root):
    """The .gitattributes half — travels with the repo; written at init/
    migrate only (a bind must never mutate the working tree mid-slice, or
    the file lands in the slice's own diff and trips G3)."""
    ga = root / ".gitattributes"
    lines = ga.read_text().splitlines() if ga.exists() else []
    for f in SUBSTRATE_UNION_MERGE:
        entry = f"{f} merge=union"
        if entry not in lines:
            lines.append(entry)
    for f in SUBSTRATE_KEYED_MERGE:
        entry = f"{f} merge=harness-substrate"
        if entry not in lines:
            lines.append(entry)
    for f in SUBSTRATE_OURS_MERGE:
        entry = f"{f} merge=ours"
        if entry not in lines:
            lines.append(entry)
    ga.write_text("\n".join(lines) + "\n")


def _config_merge_drivers(root):
    """The git-config half — repo-local, does NOT travel with clones (S8);
    re-asserted at every bind (idempotent, tree-untouching)."""
    if not (root / ".git").exists():
        return
    import subprocess
    # `ours` is NOT a built-in low-level driver (only text/binary/union
    # are) — it must be defined or the attribute silently degrades to
    # a normal text merge
    subprocess.run(["git", "-C", str(root), "config",
                    "merge.ours.driver", "true"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "config",
                    "merge.harness-substrate.name",
                    "harness keyed-by-id 3-way JSONL merge"],
                   capture_output=True)
    subprocess.run(["git", "-C", str(root), "config",
                    "merge.harness-substrate.driver",
                    f'"{sys.executable}" '
                    f'"{PLUGIN_ROOT / "bin" / "harness"}" '
                    f'merge-substrate %O %A %B'],
                   capture_output=True)


def _install_merge_drivers(root):
    _write_merge_attributes(root)
    _config_merge_drivers(root)


class _CeremonyFail(Exception):
    """A close precondition failed. `attempt` marks substantive failures
    (they count toward the auto-park cap); guard refusals do not."""

    def __init__(self, payload, attempt=True):
        self.payload = payload
        self.attempt = attempt


def _fail(payload, attempt=True):
    raise _CeremonyFail(payload, attempt)


def _reset_close_attempts(root, slice_id):
    from engine.events import Sidecar
    sidecar = Sidecar(root)
    try:
        sidecar.db.execute(
            "DELETE FROM session_state WHERE session_id='__attempts__' AND key=?",
            (slice_id,))
        sidecar.db.commit()
    finally:
        sidecar.close()
