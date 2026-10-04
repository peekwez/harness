"""G10 shared-memory guard: agents never write `.claude/memory/shared/`.

A human promotes each shared fact with `harness memory promote` (D-0.10-02).
The guard runs in the engine at pre_change, so every host adapter inherits
it. No override or exempt path applies: shared memory holds only facts a
human chose. G9 is reserved for W6's explore-isolation gate.

At pre_change G10 judges tool edits. At unit_complete (close) it judges the
slice change set, so a shell write such as `echo x > shared/a.md` blocks
too (W8-P21). A changed path passes when a human sanctioned it: its bytes
match a row in `.harness/promotions.jsonl` (written by `harness memory
promote` and `harness memory accept`), or it equals the same path on the
merge target (`landing.base`), so content merged in from there is not the
slice's write. A deletion passes when accepted or absent on the target.

The review stack's dry run over a slice diff (`payload.source == "review"`)
is skipped: close runs the unit_complete pack itself right after review.
Host events cannot set `source`; event normalization drops the key.
"""
from __future__ import annotations

from ..events import make_finding
from ..shared_memory import in_shared_dir, matches_target, sanctioned

GATE = {"id": "G10", "rule_ref": "gate:G10",
        "preferred": ("pre_change", "unit_complete"),
        "fallback": ("post_change",)}


def _target(config) -> str:
    """The branch a slice lands on: `landing.base`, default `main`."""
    landing = (config or {}).get("landing")
    base = landing.get("base") if isinstance(landing, dict) else None
    return base if isinstance(base, str) and base.strip() else "main"


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
            if (sanctioned(ctx.root, rel)
                    or matches_target(ctx.root, rel, _target(ctx.config))):
                continue
            verb = "write" if (ctx.root / rel).exists() else "delete"
            findings.append(make_finding(
                "SHARED_MEMORY_WRITE", GATE["rule_ref"],
                f"The slice changes {rel} outside harness memory promote. "
                f"Agents may not {verb} shared memory.",
                severity="block", key=rel,
                fix=f"If a human made this change, run: harness memory "
                    f"accept {rel}. Otherwise revert it and use harness "
                    f"memory promote."))
            continue
        findings.append(make_finding(
            "SHARED_MEMORY_WRITE", GATE["rule_ref"],
            f"Agents may not write {rel}.",
            severity="block", key=rel,
            fix="Ask a human to run: harness memory promote <file>"))
    return findings
