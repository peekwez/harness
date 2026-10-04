"""G10 shared-memory guard: agents never write `.claude/memory/shared/`.

A human promotes each shared fact with `harness memory promote` (D-0.10-02).
The guard runs in the engine at pre_change, so every host adapter inherits
it. No override or exempt path applies: shared memory holds only facts a
human chose. G9 is reserved for W6's explore-isolation gate.

G10 judges tool edits only. The review stack's dry run over a slice diff
(`payload.source == "review"`) is skipped: a promoted fact is committed
with the slice, and `harness memory promote` wrote it, not a tool edit.
Host events cannot set `source`; event normalization drops the key.
"""
from __future__ import annotations

from ..events import make_finding
from ..shared_memory import in_shared_dir

GATE = {"id": "G10", "rule_ref": "gate:G10",
        "preferred": ("pre_change",), "fallback": ("post_change",)}


def check(ctx) -> list:
    if ctx.payload.get("source") == "review":
        return []
    findings = []
    for path in ctx.touched_files():
        rel = ctx.rel(path)
        if not in_shared_dir(rel):
            continue
        findings.append(make_finding(
            "SHARED_MEMORY_WRITE", GATE["rule_ref"],
            f"Agents may not write {rel}.",
            severity="block", key=rel,
            fix="Ask a human to run: harness memory promote <file>"))
    return findings
