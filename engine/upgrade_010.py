"""Harness 0.10 upgrade steps: one registry, run after the schema migration.

Each workstream registers its steps in its own module (`engine/upgrade_w1.py`
and so on). This module imports those modules at the bottom, in workstream
order. A step is idempotent: after `apply`, `describe` returns `[]`.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import HarnessError

Ask = Callable[[str], bool]          # returns True when the human accepts

SKIPPED = "skipped: needs confirmation"


@dataclass(frozen=True)
class Step:
    id: str                                   # "w1.untrack-shadows"
    title: str                                # one STE-80 line for the plan
    describe: Callable[[Path], list[str]]     # pending changes; [] = nothing to do
    apply: Callable[[Path, Ask], list[str]]   # performs them; returns report lines
    destructive: bool = False                 # True -> apply must call ask() first
    # Human checks that are not changes: "check: <what to do>". Printed on
    # every run, never counted as pending work, so idempotence holds. Use it
    # for files harness must not edit (no harness marker).
    advise: Callable[[Path], list[str]] | None = None


STEPS: list[Step] = []


def advice(root: Path) -> list[dict]:
    """Advice from every step, whether or not it has changes."""
    root = Path(root)
    out = []
    for step in STEPS:
        lines = step.advise(root) if step.advise else []
        out.extend({"id": step.id, "check": line} for line in lines)
    return out


def register(step: Step) -> Step:
    """Add one step. A second step with the same id is a bug."""
    if any(existing.id == step.id for existing in STEPS):
        raise HarnessError(f"upgrade step {step.id!r} is registered twice")
    STEPS.append(step)
    return step


def plan(root: Path) -> list[dict]:
    """The steps that still have work, with the changes each would make."""
    root = Path(root)
    out = []
    for step in STEPS:
        changes = step.describe(root)
        if changes:
            out.append({"id": step.id, "title": step.title, "changes": changes})
    return out


def run(root: Path, ask: Ask, *, dry_run: bool) -> list[dict]:
    """Apply every step that has work. A dry run only describes.

    Raises:
        HarnessError: a destructive step applied without asking, or a step
            left changes undone without reporting a skip.
    """
    root = Path(root)
    results = []
    for step in STEPS:
        changes = step.describe(root)
        if not changes:
            continue
        row = {"id": step.id, "title": step.title, "changes": changes}
        if not dry_run:
            asked: list[str] = []

            def recording_ask(question: str, _asked=asked) -> bool:
                _asked.append(question)
                return ask(question)

            report = step.apply(root, recording_ask)
            if step.destructive and not asked:
                raise HarnessError(
                    f"upgrade step {step.id} is destructive but applied "
                    f"without asking. Fix the step: call ask() before any change")
            row["report"] = report
            if SKIPPED not in report:
                left = step.describe(root)
                if left:
                    raise HarnessError(
                        f"upgrade step {step.id} left changes undone: {left}. "
                        f"Fix the cause, then run: harness upgrade")
        results.append(row)
    return results


def always_yes(question: str) -> bool:
    """The `--yes` answer: accept every prompt."""
    return True


def tty_ask(question: str) -> bool:
    """Ask on stderr and read stdin. With no terminal the answer is no."""
    stdin = sys.stdin
    if stdin is None or not stdin.isatty():
        return False
    print(f"{question} [y/N] ", end="", file=sys.stderr, flush=True)
    return stdin.readline().strip().lower() in ("y", "yes")


# Workstream step modules, in workstream order. Each import registers steps.
from . import upgrade_w1  # noqa: E402,F401
from . import upgrade_w2  # noqa: E402,F401
from . import upgrade_w3  # noqa: E402,F401
from . import upgrade_w4  # noqa: E402,F401  (W4 steps)
