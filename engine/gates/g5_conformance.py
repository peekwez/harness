"""G5 registry-conform: uses ⊆ declares ∪ flagged; no reimplementation above
similarity threshold vs registry signature_digests.

DEFAULT: block; the builder may override with recorded justification (writes
an auditable `override` edge). Config g5_override: advisory | park.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..events import make_finding
from ..extractor.engine import LANG_BY_EXT, shadow_path_for
from ..registry import digest_tokens, signature_digest, similarity

GATE = {"id": "G5", "rule_ref": "gate:G5",
        "preferred": ("post_change", "unit_complete"), "fallback": ()}


def _severity(ctx) -> str:
    mode = ctx.config["gates"]["g5_override"]
    if mode == "advisory":
        return "advisory"
    if mode == "park":
        return "gate"
    return "block"  # recorded_justification (default)


def _override_targets(ctx) -> set:
    """Bare ids of overridden targets (module:/registry: prefixes stripped)."""
    from ..graph import load_edges
    s = f"slice:{ctx.work_unit_id}"
    return {e["to"].split(":", 1)[-1] for e in load_edges(ctx.root)
            if e["from"] == s and e["type"] == "override"}


def _shadow_for_touched(ctx, rel):
    from .. import HarnessError
    try:
        sp = shadow_path_for(ctx.root, ctx.root / rel)
    except HarnessError:
        return None  # poison touched row (out-of-root): never crash a gate (S5)
    if sp.exists():
        return json.loads(sp.read_text())
    return None


def check(ctx) -> list:
    if not ctx.work_unit_id:
        return []
    findings = []
    sl = ctx.slice
    declared = set(sl.get("declares_dep", []))
    overridden = _override_targets(ctx)
    registry = {e["id"]: e for e in ctx.registry}
    by_module = {e.get("module_id"): e for e in ctx.registry if e.get("module_id")}
    threshold = float(ctx.config["gates"].get("g5_similarity_threshold", 0.6))
    sev = _severity(ctx)

    touched = [ctx.rel(p) for p in ctx.touched_files()]
    if not touched:
        touched = sorted(ctx.sidecar.touched_paths(slice_id=ctx.work_unit_id))

    for rel in touched:
        if Path(rel).is_absolute():
            continue  # out-of-root/poison rows: G8 territory, never a crash
        if Path(rel).suffix.lower() not in LANG_BY_EXT:
            continue
        if rel.startswith((".harness/", "tests/", "adr/", "contracts/", "docs/")):
            continue
        shadow = _shadow_for_touched(ctx, rel)
        if shadow is None:
            continue

        # uses ⊆ declares ∪ flagged
        for imp in shadow.get("imports", []):
            target = registry.get(imp) or by_module.get(imp)
            if target is None:
                continue  # not a registry abstraction; G8 owns coverage
            tid = target["id"]
            own = next((e for e in ctx.registry if e.get("source") == rel), None)
            if own is not None and own["id"] == tid:
                continue
            if tid in declared or tid in overridden:
                continue
            findings.append(make_finding(
                "UNDECLARED_USE", GATE["rule_ref"],
                f"{rel} uses registry abstraction {tid!r} which slice "
                f"{ctx.work_unit_id} does not declare; declare it or record an "
                f"override with justification",
                severity=sev, key=rel + "|uses|" + tid))

        # reimplementation check vs registry signature_digests (declared or
        # not: copying a declared dep instead of using it is still the bug)
        new_tokens = digest_tokens(signature_digest(shadow))
        for e in ctx.registry:
            if not e.get("signature_digest"):
                continue
            if e.get("source") == rel:
                continue
            if e["id"] in overridden:
                continue
            sim = similarity(new_tokens, digest_tokens(e["signature_digest"]))
            if sim >= threshold:
                findings.append(make_finding(
                    "DUPLICATE_CANDIDATE", GATE["rule_ref"],
                    f"{rel} public surface is {sim:.0%} similar to registry entry "
                    f"{e['id']!r} ({e.get('source')}); reuse it, or override with "
                    f"recorded justification (`harness gates override`)",
                    severity=sev, key=rel + "|dup|" + e["id"]))
    return findings


def record_override(root, slice_id: str, target: str, justification: str,
                    finding_id: str | None = None,
                    rule_ref: str = "gate:G5") -> dict:
    """Builder override-and-justification: auditable edge (T3). rule_ref
    names the gate actually being overridden — hardcoding G5 falsified the
    ledger for G1/G3 overrides (field report W9)."""
    from ..graph import append_edge
    from .. import HarnessError
    if not justification or not justification.strip():
        raise HarnessError("override requires a non-empty justification (fail closed)")
    return append_edge(root, "override", f"slice:{slice_id}", target,
                       meta={"justification": justification.strip(),
                             "finding_id": finding_id,
                             "rule_ref": rule_ref or "gate:G5"})
