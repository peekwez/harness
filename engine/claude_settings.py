"""Refresh a harness-written Claude settings file without losing human edits.

`.claude/settings.json` is replaced by the template. When the old file held
something the new one lacks, the old bytes go to a gitignored backup and the
report names it. `.claude/settings.local.json` is gitignored, so a lost edit
there is gone for good: it keeps every key and list entry a human added, and
only the harness-owned values change. Any change to it gets a backup and a
check line, because no commit diff shows it.
"""
from __future__ import annotations

import json
from pathlib import Path

MARKER = "harness autonomy profile"
COMMENT = "_comment"       # the template's own text; never a human edit


def _drops(old, new) -> bool:
    """True when writing `new` over `old` loses a key, a list entry or a value."""
    if isinstance(old, dict) and isinstance(new, dict):
        return any(k != COMMENT and (k not in new or _drops(v, new[k]))
                   for k, v in old.items())
    if isinstance(old, list) and isinstance(new, list):
        return any(item not in new for item in old)
    return old != new


def drops_text(old: str, new: str) -> bool:
    """`_drops` on two JSON texts. Text that is not JSON is lost unless equal."""
    try:
        return _drops(json.loads(old), json.loads(new))
    except ValueError:
        return old != new


def _merge(old, new, owned):
    """`new`, plus the keys and list entries a human added to `old`. `owned`
    holds the template's own entries: one that the new profile dropped is not
    a human's and stays dropped."""
    if isinstance(old, dict) and isinstance(new, dict):
        out = dict(new)
        for key, value in old.items():
            if key not in new:
                out[key] = value
            else:
                sub = owned.get(key) if isinstance(owned, dict) else None
                out[key] = _merge(value, new[key], sub)
        return out
    if isinstance(old, list) and isinstance(new, list):
        theirs = owned if isinstance(owned, list) else []
        return new + [x for x in old if x not in new and x not in theirs]
    return new


def changes_text(old: str, new: str) -> bool:
    """True when `new` differs from `old` in any key, entry or value."""
    try:
        return json.loads(old) != json.loads(new)
    except ValueError:
        return old != new


def merge_local(old_text: str, new_text: str, template_text: str) -> str:
    """The settings.local.json to write. An unreadable old file is replaced;
    the caller keeps a backup of it."""
    try:
        old, new = json.loads(old_text), json.loads(new_text)
        owned = json.loads(template_text)
    except ValueError:
        return new_text
    if not isinstance(old, dict):
        return new_text
    return json.dumps(_merge(old, new, owned), indent=2) + "\n"


def refresh(root: Path, config: dict, write, keep_backup) -> dict:
    """Refresh both profiles that carry the harness marker. `write` is
    `_write_autonomy_settings`; `keep_backup` saves the old bytes."""
    report = {}
    for local, key in ((False, "settings"), (True, "settings_local")):
        name = "settings.local.json" if local else "settings.json"
        path = root / ".claude" / name
        rel = path.relative_to(root).as_posix()
        if not path.exists():
            report[key] = {"path": rel, "action": "missing"}
            continue
        old = path.read_bytes()
        if MARKER not in old.decode("utf-8", errors="replace"):
            report[key] = {"path": rel, "action": "kept",
                           "note": "not a Harness-owned profile"}
            continue
        # back up first: a write that fails half way must not lose the file
        cache = root / ".harness" / "cache"
        before = {p.name for p in cache.glob(f"{name}.pre-0.10*")}
        backup = keep_backup(root, name, old)
        write(root, quiet=True, local=local, config=config)
        entry = {"path": rel, "action": "refreshed"}
        old_text, new_text = old.decode("utf-8", errors="replace"), path.read_text()
        if local and changes_text(old_text, new_text):
            # gitignored: no diff shows the change, so any change gets a backup.
            # The merge can also bring back a template entry the human removed.
            entry["backup"] = backup
            entry["check"] = (f"check: the upgrade merged the 0.10 profile into {rel}. "
                              f"Compare the gitignored backup {backup} and remove any "
                              "entry you had dropped on purpose.")
        elif not local and drops_text(old_text, new_text):
            entry["backup"] = backup
            entry["check"] = (f"check: the refresh removed your own entries from {rel}. "
                              f"Copy them back from the gitignored backup {backup}.")
        elif Path(backup).name not in before:
            (root / backup).unlink()
        report[key] = entry
    return report
