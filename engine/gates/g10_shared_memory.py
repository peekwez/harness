"""G10 shared-memory guard: agents never write `.claude/memory/shared/`.

A human promotes each shared fact with `harness memory promote` (D-0.10-02).
The guard runs in the engine at pre_change, so every host adapter inherits
it. No override or exempt path applies: shared memory holds only facts a
human chose. G9 is reserved for W6's explore-isolation gate.

At pre_change G10 judges tool edits. At unit_complete (close) it judges the
slice change set, so a shell write such as `echo x > shared/a.md` blocks
too (W8-P21). A changed path passes when a human on this machine approved
it: its bytes match a row in the approval store (`engine/approvals.py`,
written by `harness memory promote` and `harness memory accept` after the
terminal code), or it equals the same path on the merge target
(`landing.base`), so content merged in from there is not the slice's
write. A deletion passes when accepted or absent on the target. The ledger
`.harness/promotions.jsonl` is history only: an agent can append to it.

At pre_change G10 also blocks a tool edit to the ledger.

The review stack's dry run over a slice diff (`payload.source == "review"`)
is skipped: close runs the unit_complete pack itself right after review.
Host events cannot set `source`; event normalization drops the key.
"""
from __future__ import annotations

import posixpath

from ..events import make_finding
from ..shared_memory import (LEDGER_NAME, approved_here, in_shared_dir,
                             matches_target)

GATE = {"id": "G10", "rule_ref": "gate:G10",
        "preferred": ("pre_change", "unit_complete"),
        "fallback": ("post_change",)}


def _target(config) -> str:
    """The branch a slice lands on: `landing.base`, default `main`."""
    landing = (config or {}).get("landing")
    base = landing.get("base") if isinstance(landing, dict) else None
    return base if isinstance(base, str) and base.strip() else "main"


def _is_ledger(rel: str) -> bool:
    return posixpath.normpath(rel.replace("\\", "/")).casefold() == \
        f".harness/{LEDGER_NAME}"


def check(ctx) -> list:
    if ctx.payload.get("source") == "review":
        return []
    at_close = ctx.event == "unit_complete"
    findings = []
    for path in ctx.touched_files():
        rel = ctx.rel(path)
        if not at_close and _is_ledger(rel):
            findings.append(make_finding(
                "SHARED_MEMORY_WRITE", GATE["rule_ref"],
                f"Agents may not write {rel}. Only harness memory promote "
                f"and accept add rows to it.",
                severity="block", key=rel,
                fix="Ask a human to run harness memory promote or accept "
                    "in their own terminal."))
            continue
        if not in_shared_dir(rel):
            continue
        if at_close:
            if (approved_here(ctx.root, rel)
                    or matches_target(ctx.root, rel, _target(ctx.config))):
                continue
            verb = "write" if (ctx.root / rel).exists() else "delete"
            findings.append(make_finding(
                "SHARED_MEMORY_WRITE", GATE["rule_ref"],
                f"The slice changes {rel} outside harness memory promote. "
                f"Agents may not {verb} shared memory.",
                severity="block", key=rel,
                fix=f"If a human made this change, ask them to run "
                    f"harness memory accept {rel} in their own terminal. "
                    f"Otherwise revert it and use harness memory promote."))
            continue
        findings.append(make_finding(
            "SHARED_MEMORY_WRITE", GATE["rule_ref"],
            f"Agents may not write {rel}.",
            severity="block", key=rel,
            fix="Ask a human to run harness memory promote <file> in "
                "their own terminal."))
    return findings
