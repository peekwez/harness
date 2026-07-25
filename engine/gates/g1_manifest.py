"""G1 manifest-complete: required artifacts for the active work unit exist."""
from __future__ import annotations

from fnmatch import fnmatch

from ..events import make_finding
from ..registry import validate_manifests

GATE = {"id": "G1", "rule_ref": "gate:G1",
        "preferred": ("session_start", "pre_change"), "fallback": ("post_change",)}

REQUIRED_SUBSTRATE = ("config.yaml", "schema_version", "registry.jsonl",
                      "decisions.jsonl")


def check(ctx) -> list:
    findings = []
    hdir = ctx.root / ".harness"
    for name in REQUIRED_SUBSTRATE:
        if not (hdir / name).exists():
            findings.append(make_finding(
                "MANIFEST_INCOMPLETE", GATE["rule_ref"],
                f".harness/{name} missing — substrate incomplete; run /harness:init",
                severity="block", key=name))
    if findings:
        return findings  # registry unreadable; fail loud on the substrate first
    pending = set()
    if ctx.work_unit_id:
        pending = set(ctx.slice.get("predicted_files", []) +
                      ctx.slice.get("acceptance", []))
    findings.extend(validate_manifests(ctx.root, ctx.registry, pending=pending))
    if ctx.work_unit_id:
        sl = ctx.slice
        event_files = {ctx.rel(p) for p in ctx.touched_files()}
        for t in sl.get("acceptance", []):
            # a glob needs >= 1 REAL match: an existing dir with zero
            # matching tests is not red-test-first (S7 fail-open)
            candidates = list(ctx.root.glob(t)) if "*" in t else \
                ([ctx.root / t] if (ctx.root / t).exists() else [])
            if not candidates:
                # the write that CREATES the acceptance test must not be
                # blocked by its own absence (W9 chicken-and-egg) — builders
                # were bootstrapping via bash heredoc, bypassing edit tracking
                creating = (any(fnmatch(f, t) for f in event_files)
                            if "*" in t else t in event_files)
                if creating:
                    continue
                findings.append(make_finding(
                    "MANIFEST_INCOMPLETE", GATE["rule_ref"],
                    f"slice {sl['id']}: acceptance test {t!r} missing — "
                    f"slices start from red acceptance tests",
                    severity="block", key=sl["id"] + "|" + t))
    return findings
