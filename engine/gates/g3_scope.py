"""G3 spec-bound: touched file ∈ declared/predicted set.

DEFAULT allow_with_findings; the unit cannot close until the declaration is
reconciled. Config g3_mode: block | radius (same-package auto-allow).
Non-goal boundaries compiled from Phase 0 always block.
"""
from __future__ import annotations

from fnmatch import fnmatch
from pathlib import PurePosixPath

from ..events import make_finding

GATE = {"id": "G3", "rule_ref": "gate:G3",
        "preferred": ("pre_change",), "fallback": ("post_change",)}

# Authored substrate + meta surfaces are Phase-0-editable and never count as
# slice wandering: docs/ included per field report #18/#21.
# `.claude/` is harness-provisioned host config (the autonomy profile
# `harness start` writes into the slice's worktree) — substrate, not slice work.
SUBSTRATE_PREFIXES = (".harness/", "adr/", "contracts/", ".github/", "tests/",
                      "docs/", ".claude/")


def _overridden(ctx) -> set:
    """Bare ids of recorded overrides for this slice (boundary:B-x, file:path,
    registry:x — prefix stripped). G3 consults the same override ledger as G5
    (field report #2-recurrence/#21)."""
    if not ctx.work_unit_id:
        return set()
    from ..graph import load_edges
    s = f"slice:{ctx.work_unit_id}"
    return {e["to"].split(":", 1)[-1] for e in load_edges(ctx.root)
            if e["from"] == s and e["type"] == "override"}


def _declared_set(ctx) -> set:
    sl = ctx.slice
    declared = set(sl.get("predicted_files", []))
    registry = {e["id"]: e for e in ctx.registry}
    for did in sl.get("declares_dep", []):
        entry = registry.get(did)
        if entry and entry.get("source"):
            declared.add(entry["source"])
    declared.update(sl.get("acceptance", []))
    return declared


def check(ctx) -> list:
    findings = []
    touched = [ctx.rel(p) for p in ctx.touched_files()]
    overridden = _overridden(ctx)

    # Non-goal boundaries always bind, slice or no slice — but a recorded
    # override (boundary id or file path) downgrades the block to an
    # auditable advisory, same escape hatch as G5.
    for rel in touched:
        for b in ctx.boundaries:
            for pat in b.get("patterns", []):
                if not fnmatch(rel, pat):
                    continue
                if b.get("id") in overridden or rel in overridden:
                    findings.append(make_finding(
                        "NON_GOAL_VIOLATION",
                        b.get("rule_ref") or f"adr:{b.get('source_adr', 'phase0')}",
                        f"{rel} matches non-goal boundary {pat!r} but carries a "
                        f"recorded override (audited)",
                        severity="advisory", key=rel + "|" + pat + "|ovr"))
                    continue
                findings.append(make_finding(
                    "NON_GOAL_VIOLATION",
                    b.get("rule_ref") or f"adr:{b.get('source_adr', 'phase0')}",
                    f"{rel} matches non-goal boundary {pat!r}: {b.get('text', '')} "
                    f"(override with `harness gates override --target "
                    f"boundary:{b.get('id')}` + justification)",
                    severity="block", key=rel + "|" + pat))

    if not ctx.work_unit_id:
        return findings

    mode = ctx.config["gates"]["g3_mode"]
    declared = _declared_set(ctx)
    declared_dirs = {str(PurePosixPath(d).parent) for d in declared}
    for rel in touched:
        if rel.startswith(SUBSTRATE_PREFIXES):
            continue
        if rel in declared or any(fnmatch(rel, d) for d in declared if "*" in d):
            continue
        if rel in overridden:
            continue  # reconciled via recorded override
        if mode == "radius" and str(PurePosixPath(rel).parent) in declared_dirs:
            continue  # same-package auto-allow
        severity = "block" if mode == "block" else "gate"
        findings.append(make_finding(
            "UNDECLARED_FILE", GATE["rule_ref"],
            f"{rel} is not in slice {ctx.work_unit_id}'s declared/predicted set; "
            f"amend the slice declaration (reconciliation required before close-slice)",
            severity=severity, key=rel + "|" + ctx.work_unit_id))
    return findings
