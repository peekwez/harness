"""What `harness upgrade` reports: changed files, final checks, the step that
owns each failure, the lines a human must check, and one commit proposal.

Nothing in this module changes a file or the git index.
"""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from engine import IGNORED_DIRS, HarnessError, sha256_file

COMMIT_MESSAGE = "harness: upgrade to 0.10"
CHECK = "check: "
NEEDS_CONFIRMATION = "needs confirmation"
# gitignored machine state: never part of the upgrade's file report
MACHINE_STATE = (".harness/cache/", ".harness/sidecar.db")


def _git(root, *args) -> subprocess.CompletedProcess:
    done = subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise HarnessError(f"git {args[0]} failed in {root}. "
                           "Repair the repository, then run: harness upgrade")
    return done


def _few(paths, limit=3) -> str:
    shown = ", ".join(list(paths)[:limit])
    extra = len(paths) - limit
    return f"{shown} and {extra} more" if extra > 0 else shown


def _is_repo(root) -> bool:
    return (Path(root) / ".git").exists()


def _nul_list(text: str) -> list[str]:
    return [p for p in text.split("\0") if p]


def _listed(root: Path) -> list[str]:
    if _is_repo(root):
        out = _git(root, "ls-files", "-z", "--cached", "--others",
                   "--exclude-standard").stdout
        return sorted(set(_nul_list(out)))
    skip = IGNORED_DIRS - {".harness"}
    paths = []
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if path.is_dir() or any(part in skip for part in rel.parts):
            continue
        paths.append(rel.as_posix())
    return sorted(paths)


def snapshot(root) -> dict:
    """Map each tracked or untracked, non-ignored path to its sha256.

    A tracked path that is gone from disk maps to None.
    """
    root = Path(root)
    out = {}
    for rel in _listed(root):
        if rel.startswith(MACHINE_STATE):
            continue
        path = root / rel
        out[rel] = sha256_file(path) if path.is_file() else None
    return out


def changed_files(before: dict, after: dict) -> dict:
    old = {k for k, v in before.items() if v is not None}
    new = {k for k, v in after.items() if v is not None}
    return {"added": sorted(new - old),
            "modified": sorted(k for k in old & new if before[k] != after[k]),
            "removed": sorted(old - new)}


def staged_paths(root) -> list[str]:
    if not _is_repo(root):
        return []
    return sorted(_nul_list(_git(root, "diff", "--cached", "--name-only", "--no-renames", "-z").stdout))


def dirty_paths(root) -> list[str]:
    if not _is_repo(root):
        return []
    entries = _nul_list(_git(root, "status", "--porcelain=v1", "-z",
                             "--untracked-files=all").stdout)
    paths, skip_next = [], False
    for entry in entries:
        if skip_next:            # the source path of a rename or copy
            skip_next = False
            continue
        paths.append(entry[3:])
        skip_next = entry[0] in "RC"
    return sorted(paths)


def step_lines(row: dict) -> list[str]:
    lines = row.get("report")
    if lines is None:
        lines = row.get("changes", [])
    return [str(line) for line in lines]


def human_checks(steps, *, pending, staged_before, dirty_before, files,
                 checks, is_repo, advice=()) -> list[str]:
    out = [f"{row['id']}: {row['check']}" for row in advice]
    for row in steps:
        for line in step_lines(row):
            if line.startswith(CHECK) or NEEDS_CONFIRMATION in line:
                out.append(f"{row['id']}: {line}")
    if pending:
        out.append(f"{CHECK}steps {_few(pending)} still have changes. "
                   "Run: harness upgrade --yes")
    touched = set(files["added"]) | set(files["modified"]) | set(files["removed"])
    mixed = sorted(set(dirty_before) & touched)
    if mixed:
        out.append(f"{CHECK}you had uncommitted edits in {_few(mixed)}. "
                   "Review them before you commit.")
    if staged_before:
        out.append(f"{CHECK}the index held staged changes before the upgrade: "
                   f"{_few(staged_before)}. Commit or unstage them first.")
    deps = ((checks or {}).get("doctor") or {}).get("deps_missing") or []
    if deps:
        out.append(f"{CHECK}engine dependencies are missing: {' '.join(deps)}. "
                   f"Run: pip install {' '.join(deps)}")
    if not is_repo:
        out.append(f"{CHECK}this folder is not a git repository. "
                   "Commit the upgrade with your own tool.")
    return out


def commit_proposal(root, files) -> dict | None:
    """The one commit the human runs from the repo root. Paths that are gone
    from disk and from the index are already staged deletions."""
    root = Path(root)
    if not _is_repo(root):
        return None
    changed = sorted(set(files["added"]) | set(files["modified"]) | set(files["removed"]))
    if not changed:
        return None
    index = set(_nul_list(_git(root, "ls-files", "-z", "--cached").stdout))
    paths = [p for p in changed if (root / p).exists() or p in index]
    commit = f'git commit -m "{COMMIT_MESSAGE}"'
    command = (f"git --literal-pathspecs add -A -- {' '.join(shlex.quote(p) for p in paths)} && {commit}"
               if paths else commit)
    return {"message": COMMIT_MESSAGE, "paths": paths, "cwd": str(root),
            "command": command}
