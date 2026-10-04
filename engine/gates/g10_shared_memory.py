"""G10 shared-memory guard: agents never write `.claude/memory/shared/`.

A human promotes each shared fact with `harness memory promote` (D-0.10-02).
The guard runs in the engine at pre_change, so every host adapter inherits
it. No override or exempt path applies: shared memory holds only facts a
human chose. G9 is reserved for W6's explore-isolation gate.

At pre_change G10 judges tool edits. At unit_complete (close) it judges the
slice change set, so a shell write such as `echo x > shared/a.md` blocks
too (W8-P21). There a path passes only when its bytes match a row that
`harness memory promote` wrote to `.harness/promotions.jsonl`; a
deleted shared file always blocks.

The review stack's dry run over a slice diff (`payload.source == "review"`)
is skipped: close runs the unit_complete pack itself right after review.
Host events cannot set `source`; event normalization drops the key.
"""
from __future__ import annotations

from ..events import make_finding
from ..shared_memory import in_shared_dir, sanctioned

GATE = {"id": "G10", "rule_ref": "gate:G10",
        "preferred": ("pre_change", "unit_complete"),
        "fallback": ("post_change",)}


def check(ctx) -> list:
    if ctx.payload.get("source") == "review":
        return []
    at_close = ctx.event == "unit_complete"
    findings = []
    for path in ctx.touched_files():
        rel = ctx.rel(path)
        if not in_shared_dir(rel):
            continue
        if at_close:
            if sanctioned(ctx.root, rel):
                continue
            verb = "write" if (ctx.root / rel).exists() else "delete"
            findings.append(make_finding(
                "SHARED_MEMORY_WRITE", GATE["rule_ref"],
                f"The slice changes {rel} outside harness memory promote. "
                f"Agents may not {verb} shared memory.",
                severity="block", key=rel,
                fix=f"Revert the change to {rel}. Then ask a human to run: "
                    f"harness memory promote <file>"))
            continue
        findings.append(make_finding(
            "SHARED_MEMORY_WRITE", GATE["rule_ref"],
            f"Agents may not write {rel}.",
            severity="block", key=rel,
            fix="Ask a human to run: harness memory promote <file>"))
    return findings
