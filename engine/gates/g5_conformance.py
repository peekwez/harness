"""G5 registry-conform: uses within declares; no reimplementation above the
similarity threshold vs registry signature_digests.

0.10 (D-0.10-01): every G5 finding is advisory. Close still reconciles
uses within declares (`uses_vs_declares`), and review rubrics R-uses and
R-dup still block there. An override records an auditable edge.
"""
from __future__ import annotations

from pathlib import Path

from ..events import make_finding
from . import exempt
from ..extractor import engine as _ex
from ..extractor.engine import LANG_BY_EXT, RegistryIndex, shadow_for
from ..registry import digest_tokens, signature_digest, similarity

GATE = {"id": "G5", "rule_ref": "gate:G5",
        "preferred": ("post_change", "unit_complete"), "fallback": ()}


def _override_targets(ctx) -> set:
    """Bare ids of overridden targets (module:/registry: prefixes stripped)."""
    from ..graph import override_targets
    return override_targets(ctx.root, ctx.work_unit_id, "gate:G5",
                            {"module", "registry"})


def _shadow_for_touched(ctx, rel, known_modules, ignored):
    from .. import HarnessError
    try:
        return shadow_for(ctx.root, ctx.root / rel, ctx.config,
                          known_modules=known_modules, ignored=ignored)
    except HarnessError:
        return None  # poison touched row (out-of-root): never crash a gate (S5)


def check(ctx) -> list:
    if not ctx.work_unit_id:
        return []
    findings = []
    sl = ctx.slice
    declared = set(sl.get("declares_dep", []))
    overridden = _override_targets(ctx)
    index = RegistryIndex(ctx.registry)
    threshold = float(ctx.config["gates"].get("g5_similarity_threshold", 0.6))
    sev = "advisory"

    touched = [ctx.rel(p) for p in ctx.touched_files()]
    if not touched:
        touched = sorted(ctx.sidecar.touched_paths(slice_id=ctx.work_unit_id))

    # a malformed `shadows` config fails loud here, outside the poison-row
    # catch below (a swallowed config error would silently disable G5)
    _ex.validate_shadow_config(ctx.config)
    candidates = [r for r in touched if not Path(r).is_absolute()]
    # module ids only matter for a Python file: scan once, and only then
    known_modules = (_ex.python_module_ids(ctx.root, ctx.config)
                     if any(_ex.LANG_BY_EXT.get(Path(r).suffix.lower())
                            == "python" for r in candidates) else None)
    ignored = _ex.git_ignored_set(ctx.root, candidates)           # once

    for rel in touched:
        if Path(rel).is_absolute():
            continue  # out-of-root/poison rows: never a crash
        if Path(rel).suffix.lower() not in LANG_BY_EXT:
            continue
        if exempt(rel, ctx.config):
            continue
        shadow = _shadow_for_touched(ctx, rel, known_modules, ignored)
        if shadow is None:
            continue

        # uses ⊆ declares ∪ flagged
        for imp in shadow.get("imports", []):
            # longest dotted prefix: `kente.config.secrets` is the
            # `kente.config` entry, never the bare `kente` one (D-008)
            target = index.match(imp)
            if target is None:
                continue  # not a registry abstraction
            tid = target["id"]
            own = next((e for e in ctx.registry if e.get("source") == rel), None)
            if own is not None and own["id"] == tid:
                continue
            if tid in declared or tid in overridden:
                continue
            findings.append(make_finding(
                "UNDECLARED_USE", GATE["rule_ref"],
                f"{rel} uses registry entry {tid!r}, which slice "
                f"{ctx.work_unit_id} does not declare.",
                severity=sev, key=rel + "|uses|" + tid,
                fix=f"Add {tid} to declares_dep of slice {ctx.work_unit_id}, "
                    f"or run: harness gates override --slice "
                    f"{ctx.work_unit_id} --target registry:{tid} "
                    f"--justification \"<why>\""))

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
                    f"{rel} public interface is {sim:.0%} similar to registry "
                    f"entry {e['id']!r} ({e.get('source')}).",
                    severity=sev, key=rel + "|dup|" + e["id"],
                    fix=f"Reuse {e['id']}, or run: harness gates override "
                        f"--slice {ctx.work_unit_id} --target "
                        f"registry:{e['id']} --justification \"<why>\""))
    return findings


def record_override(root, slice_id: str, target: str, justification: str,
                    finding_id: str | None = None,
                    rule_ref: str | None = None) -> dict:
    """Builder override-and-justification: auditable edge (T3). rule_ref
    names the gate actually being overridden — hardcoding G5 falsified the
    ledger for G1/G3 overrides (field report W9)."""
    from ..graph import append_edge
    from .. import HarnessError
    if not justification or not justification.strip():
        raise HarnessError("override requires a non-empty justification (fail closed)")
    inferred = "gate:G3" if target.partition(":")[0] in {"file", "boundary"} else "gate:G5"
    from ..overrides import canonical_target
    rule_ref = rule_ref or inferred
    canonical = canonical_target(root, target, rule_ref, justification)
    meta = {"justification": justification.strip(), "finding_id": finding_id,
            "rule_ref": rule_ref}
    if canonical != target:
        meta["requested_target"] = target
    return append_edge(root, "override", f"slice:{slice_id}", canonical, meta=meta)
