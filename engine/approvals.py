"""This machine's record of the shared-memory writes a human approved.

`harness memory promote` and `harness memory accept` write here after the
human types the code at a terminal (`human.confirm`), and G10 at close
trusts a changed shared-memory file only when its bytes match a row here
for the same repo. The ledger in `.harness/promotions.jsonl` stays the
team's history; this store is the check an agent cannot satisfy.

The store lives in the user's home folder, outside every worktree, so the
shipped sandbox (writes only inside the worktree) refuses an agent's write
to it. The home folder comes from the OS user record, not `$HOME` or
`$XDG_CONFIG_HOME`, so an agent cannot point it somewhere it can write.

Limits: without the sandbox, an agent's shell can write the store. An
agent that runs its own copy of the close checks can skip them. CI does
not read the store; G10 at close runs on the human's machine.
"""
from __future__ import annotations

import json
import os
import pwd
from pathlib import Path

from . import HarnessError, now_iso

# Tests point this at a temp file. The engine never reads an env var or a
# flag for it, so a caller cannot redirect the store.
_STORE_OVERRIDE: Path | None = None


def store_path() -> Path:
    """`~/.config/harness/approvals.jsonl`, home from the OS user record."""
    if _STORE_OVERRIDE is not None:
        return Path(_STORE_OVERRIDE)
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    return home / ".config" / "harness" / "approvals.jsonl"


def repo_key(root) -> str:
    """The main worktree's real path: all worktrees of a repo share it."""
    from .shared_memory import main_repo_root
    return os.path.realpath(main_repo_root(root))


def ensure_writable(action: str) -> Path:
    """Open the store for append once, or refuse before any write.

    Raises:
        HarnessError: the store cannot be created or appended to, as in a
            sandbox that confines writes to the worktree.
    """
    path = store_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8"):
            pass
    except OSError as err:
        raise HarnessError(
            f"{action}: cannot write the approval store {path} "
            f"({err.__class__.__name__}), so nothing was written. Fix: run "
            f"it in your own terminal.") from None
    return path


def record(root, rel: str, sha256: str | None, by: str) -> None:
    """Append one approval: these bytes (or this deletion) of `rel`."""
    row = {"repo": repo_key(root), "path": rel, "sha256": sha256,
           "at": now_iso(), "by": by}
    if sha256 is None:
        row["deleted"] = True
    with open(store_path(), "a", encoding="utf-8") as out:
        out.write(json.dumps(row, sort_keys=True) + "\n")


def _rows(root, key: str):
    path = store_path()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    repo = repo_key(root)
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("repo") == repo and key(row):
            rows.append(row)
    return rows


def approved(root, rel: str, sha256: str | None, norm) -> bool:
    """True when a human on this machine approved these bytes of `rel`.

    `sha256` None asks about a deletion: the last row for the path must
    record one. `norm` maps a path to its ledger key.
    """
    want = norm(rel)
    rows = _rows(root, lambda r: norm(str(r.get("path", ""))) == want)
    if sha256 is None:
        return bool(rows) and rows[-1].get("deleted") is True
    return any(r.get("sha256") == sha256 for r in rows)
