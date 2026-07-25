"""Permission policy: the gates ARE the approval layer.

Approval prompts were never the enforcement layer in a harness repo — the
pre-change gates and CI verify are. So inside a bound slice the engine
answers the host's permission question itself: work that the gates would
allow is auto-approved, and nothing else is. Policy lives here (engine),
never in the adapters, which only translate.

Two surfaces:
- `paths_in_scope` — file work inside the slice's declared/predicted set.
- `command_allowed` — the slice loop's command surface (harness, tests,
  local git). Egress (push/remote/fetch/clone) is never auto-approved, and
  neither is anything unrecognized: those fall through to the human.
"""
from __future__ import annotations

import re
import shlex
from fnmatch import fnmatch

from .gates.g3_scope import SUBSTRATE_PREFIXES

# git subcommands that stay on this machine
GIT_LOCAL = {
    "status", "diff", "log", "show", "add", "commit", "rev-parse", "notes",
    "worktree", "checkout", "switch", "branch", "merge", "stash", "cat-file",
    "ls-files", "config", "restore", "reset", "rm", "mv", "tag", "apply",
    "cherry-pick", "rebase", "describe", "blame", "grep", "init",
}
# never auto-approved: anything that talks to a remote
GIT_EGRESS = {"push", "remote", "clone", "fetch", "pull", "submodule",
              "request-pull", "send-email"}

TEST_RUNNERS = ("pytest", "python -m pytest", "python3 -m pytest",
                ".venv/bin/pytest", ".venv/bin/python -m pytest",
                "make test", "make verify", "make replay")

# splitting on shell operators: EVERY segment must be allowed, mirroring how
# hosts evaluate chained commands
_SPLIT = re.compile(r"&&|\|\||[;\n|]")
# command substitution can hide anything — never auto-approve a command
# carrying it (this is also why the skills use `--commit HEAD`)
_SUBSTITUTION = re.compile(r"\$\(|`|<\(")


def _segment_allowed(seg: str, harness_bin: str | None) -> bool:
    seg = seg.strip()
    if not seg:
        return True
    try:
        parts = shlex.split(seg)
    except ValueError:
        return False          # unbalanced quotes: not something to auto-approve
    if not parts:
        return True
    head = parts[0]
    if head in ("cd", "true", "echo", "ls", "pwd"):
        return True
    base = head.rsplit("/", 1)[-1]
    if base == "harness" or (harness_bin and head.strip('"\'') == harness_bin):
        return True
    if base in ("python", "python3") and parts[1:3] == ["-m", "pytest"]:
        return True
    if base in ("pytest",):
        return True
    if base == "make" and len(parts) > 1 and parts[1] in ("test", "verify", "replay"):
        return True
    if base == "git":
        sub = next((p for p in parts[1:] if not p.startswith("-")), None)
        return sub in GIT_LOCAL and sub not in GIT_EGRESS
    return any(seg.startswith(pfx) for pfx in TEST_RUNNERS)


def command_allowed(command: str, harness_bin: str | None = None) -> tuple:
    """(allow, reason). Conservative by construction: unknown commands are
    NOT denied here — they simply are not auto-approved, so the host's
    normal permission flow (and the user) decides."""
    if not command or not command.strip():
        return False, "empty command"
    if _SUBSTITUTION.search(command):
        return False, ("command substitution is never auto-approved — use "
                       "plain commands (e.g. `--commit HEAD`)")
    segments = _SPLIT.split(command)
    for seg in segments:
        if not _segment_allowed(seg, harness_bin):
            return False, f"segment not in the slice loop's command surface: {seg.strip()!r}"
    return True, "slice loop command surface"


def declared_set(slice_row: dict, registry: list) -> set:
    declared = set(slice_row.get("predicted_files", []))
    declared.update(slice_row.get("acceptance", []))
    by_id = {e["id"]: e for e in registry}
    for did in slice_row.get("declares_dep", []):
        entry = by_id.get(did)
        if entry and entry.get("source"):
            declared.add(entry["source"])
    return declared


def paths_in_scope(slice_row: dict, registry: list, rels) -> bool:
    """True when every path is substrate or inside the slice's declaration.
    Wandering keeps its prompt — auto-approval is scoped to what the slice
    said it would touch, which is exactly what G3 reconciles at close."""
    declared = declared_set(slice_row, registry)
    globs = [d for d in declared if "*" in d]
    for rel in rels:
        if rel.startswith(SUBSTRATE_PREFIXES):
            continue
        if rel in declared or any(fnmatch(rel, g) for g in globs):
            continue
        return False
    return True
