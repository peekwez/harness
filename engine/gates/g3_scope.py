"""G3 scope: touched files against the slice declaration and the non-goals.

0.10 (D-0.10-01): a file outside the declaration is an advisory finding.
A non-goal blocks only when a `gates.extra` gate cites its boundary id or
rule ref in `GATE["cites"]`; otherwise it is advisory. A recorded override
downgrades a cited block to an audited advisory. Config `g3_mode: radius`
also skips files in a declared file's directory. Files under
`gates.exempt_paths` raise no scope finding.
"""
from __future__ import annotations

from fnmatch import fnmatch
from pathlib import PurePosixPath

from ..events import make_finding
from ..findings import clip_words
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


def _non_goal_finding(rel, pat, boundary, overridden, cited,
                      slice_id=None) -> dict:
    """One NON_GOAL_VIOLATION. Blocks only when a gates.extra gate cites the
    boundary id or its rule ref; a recorded override downgrades a block to
    an audited advisory (spec 4.1)."""
    rule_ref = (boundary.get("rule_ref")
                or f"adr:{boundary.get('source_adr', 'phase0')}")
    bid = boundary.get("id")
    if bid in overridden or rel in overridden:
        return make_finding(
            "NON_GOAL_VIOLATION", rule_ref,
            f"{rel} matches non-goal {bid} ({pat}); a recorded override "
            f"accepts it.",
            severity="advisory", key=rel + "|" + pat + "|ovr")
    if bid in cited or rule_ref in cited:
        return make_finding(
            "NON_GOAL_VIOLATION", rule_ref,
            f"{rel} matches non-goal {bid} ({pat}): "
            f"{clip_words(boundary.get('text', ''), 12)}",
            severity="block", key=rel + "|" + pat,
            fix=f"Move the change out of {pat}, or run: harness gates "
                f"override --slice {slice_id or '<slice>'} "
                f"--target boundary:{bid} --justification \"<why>\"")
    return make_finding(
        "NON_GOAL_VIOLATION", rule_ref,
        f"{rel} is inside non-goal {bid}, which no gate cites, so it only "
        f"warns.",
        severity="advisory", key=rel + "|" + pat + "|uncited",
        fix=f"Cite {rule_ref} in a gates.extra "
            f"GATE[\"cites\"].")


def check(ctx) -> list:
    findings = []
    touched = [ctx.rel(p) for p in ctx.touched_files()]
    overridden = _overridden(ctx)

    # Non-goals bind slice or no slice; only cited ones block (spec 4.1).
    for rel in touched:
        for b in ctx.boundaries:
            for pat in b.get("patterns", []):
                if fnmatch(rel, pat):
                    findings.append(_non_goal_finding(rel, pat, b, overridden,
                                                      ctx.cited,
                                                      ctx.work_unit_id))

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
            continue  # a recorded override silences the advisory
        if mode == "radius" and str(PurePosixPath(rel).parent) in declared_dirs:
            continue  # same-package auto-allow
        findings.append(make_finding(
            "UNDECLARED_FILE", GATE["rule_ref"],
            f"{rel} is outside the declared files of slice "
            f"{ctx.work_unit_id}.",
            severity="advisory", key=rel + "|" + ctx.work_unit_id,
            fix=f"harness gates override --slice {ctx.work_unit_id} "
                f"--target file:{rel} --justification \"<why>\"."))
    return findings
