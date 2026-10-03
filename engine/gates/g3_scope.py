"""G3 scope: touched files against the slice declaration and the non-goals.

0.10 (D-0.10-01): a file outside the declaration is an advisory finding.
Config `g3_mode: radius` also skips files in a declared file's directory.
Files under `gates.exempt_paths` raise no scope finding.
"""
from __future__ import annotations

from fnmatch import fnmatch
from pathlib import PurePosixPath

from ..events import make_finding
from . import exempt

GATE = {"id": "G3", "rule_ref": "gate:G3",
        "preferred": ("pre_change",), "fallback": ("post_change",)}

def _overridden(ctx) -> set:
    """Bare ids of recorded overrides for this slice (boundary:B-x, file:path,
    registry:x — prefix stripped). G3 consults the same override ledger as G5
    (field report #2-recurrence/#21)."""
    if not ctx.work_unit_id:
        return set()
    from ..graph import override_targets
    return override_targets(ctx.root, ctx.work_unit_id, "gate:G3",
                            {"file", "boundary"})


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

    mode = ctx.config["gates"].get("g3_mode", "allow_with_findings")
    declared = _declared_set(ctx)
    declared_dirs = {str(PurePosixPath(d).parent) for d in declared}
    for rel in touched:
        if exempt(rel, ctx.config):
            continue
        if rel in declared or any(fnmatch(rel, d) for d in declared if "*" in d):
            continue
        if rel in overridden:
            continue  # reconciled via recorded override
        if mode == "radius" and str(PurePosixPath(rel).parent) in declared_dirs:
            continue  # same-package auto-allow
        findings.append(make_finding(
            "UNDECLARED_FILE", GATE["rule_ref"],
            f"G3: {rel} is not in the declared files of slice "
            f"{ctx.work_unit_id}. Add it to predicted_files.",
            severity="advisory", key=rel + "|" + ctx.work_unit_id))
    return findings
