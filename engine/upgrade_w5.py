"""W5 upgrade step (spec 12 step 9): mark in-flight slices legacy.

A slice that is not closed at upgrade time started before 0.10. It has no
red record and no statement links, so close skips checks 3 to 5 for it.
Rows that 0.10's `backlog add` writes always carry `verifies`, so a second
upgrade run never marks a new slice.
"""
from __future__ import annotations

from pathlib import Path

from . import harness_dir, read_jsonl, write_jsonl
from .upgrade_010 import Ask, Step, register


def _backlog(root: Path) -> Path:
    return harness_dir(root) / "backlog.jsonl"


def _pending(root: Path) -> list[dict]:
    path = _backlog(root)
    if not path.exists():
        return []
    return [row for row in read_jsonl(path)
            if row.get("status") != "closed"
            and "legacy_verification" not in row
            and "verifies" not in row]


def _describe(root: Path) -> list[str]:
    return [f"mark slice {row['id']} legacy_verification: true" for row in
            _pending(root)]


def _apply(root: Path, ask: Ask) -> list[str]:
    pending = {row["id"] for row in _pending(root)}
    if not pending:
        return []
    rows = read_jsonl(_backlog(root))
    for row in rows:
        if row.get("id") in pending:
            row["legacy_verification"] = True
    write_jsonl(_backlog(root), rows)
    return [f"slice {sid}: legacy_verification: true"
            for sid in sorted(pending)]


LEGACY_STEP = register(Step(
    id="w5.legacy-verification",
    title="Mark each slice that is not closed legacy_verification: true.",
    describe=_describe,
    apply=_apply,
))
