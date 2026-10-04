"""G6 interface-drift: public-symbol shadow diff since slice start.

Blocks unit_complete until acknowledged; the ack is recorded as an edge.
"""
from __future__ import annotations

from pathlib import Path

from ..events import make_finding
from ..findings import clip_words
from ..registry import public_symbols

GATE = {"id": "G6", "rule_ref": "gate:G6",
        "preferred": ("unit_complete",), "fallback": ()}


def _acked(ctx) -> set:
    from ..graph import load_edges
    s = f"slice:{ctx.work_unit_id}"
    return {e["to"] for e in load_edges(ctx.root)
            if e["from"] == s and e["type"] == "override"
            and e.get("meta", {}).get("rule_ref") == "gate:G6"}


def check(ctx) -> list:
    if not ctx.work_unit_id:
        return []
    from ..baseline import ensure_baseline
    from .. import HarnessError
    try:
        ensure_baseline(ctx.root, ctx.sidecar, ctx.work_unit_id)
    except HarnessError as exc:
        return [make_finding(
            "MISSING_DRIFT_BASELINE", GATE["rule_ref"],
            f"slice {ctx.work_unit_id} has no interface baseline: "
            f"{clip_words(str(exc), 14)}",
            severity="block", key=ctx.work_unit_id,
            fix=f"Bind the slice before you change code: harness slice "
                f"--slice {ctx.work_unit_id}")]
    baseline = ctx.sidecar.snapshot_get(ctx.work_unit_id)
    if not baseline:
        return []
    findings = []
    acked = _acked(ctx)
    registry = {e["id"]: e for e in ctx.registry}
    from ..extractor import engine as _ex
    _ex.validate_shadow_config(ctx.config)
    # module ids only matter for a Python source: scan once, and only then
    python_entries = any(
        _ex.LANG_BY_EXT.get(Path(registry[m].get("source") or "").suffix.lower())
        == "python" for m in baseline if m in registry)
    known_modules = (_ex.python_module_ids(ctx.root, ctx.config)
                     if python_entries else None)
    ignored = _ex.git_ignored_set(
        ctx.root, [e["source"] for e in registry.values() if e.get("source")])
    for module_id, old in sorted(baseline.items()):
        entry = registry.get(module_id)
        if entry is None:
            continue
        if not isinstance(old, dict):
            # legacy list-format baseline (no source_hash): a symbol diff
            # against it is indistinguishable from extractor format skew —
            # skip rather than demand acks for non-events (W8)
            continue
        old_syms = old.get("symbols") or []
        new_syms = public_symbols(ctx.root, entry, ctx.config,
                               known_modules=known_modules, ignored=ignored)
        if new_syms is None or new_syms == old_syms:
            continue
        # symbols changed but source bytes did not: extractor version skew,
        # not interface drift — the ack ledger stays clean (W8)
        from .. import sha256_file
        src = ctx.root / entry["source"] if entry.get("source") else None
        cur_hash = sha256_file(src) if src is not None and src.is_file() else None
        if old.get("source_hash") and cur_hash == old["source_hash"]:
            continue
        if f"module:{module_id}" in acked:
            continue
        added = sorted(set(new_syms) - set(old_syms))
        removed = sorted(set(old_syms) - set(new_syms))
        findings.append(make_finding(
            "INTERFACE_DRIFT", GATE["rule_ref"],
            f"public interface of {module_id!r} changed since slice start: "
            f"{len(added)} added, {len(removed)} removed.",
            severity="block", key=ctx.work_unit_id + "|" + module_id,
            inject=[f"added: {added[:5]}", f"removed: {removed[:5]}"],
            fix=f"Run: harness gates ack-drift --slice {ctx.work_unit_id} "
                f"--module {module_id}"))
    return findings


def acknowledge(root, slice_id: str, module_id: str, note: str = "") -> dict:
    from ..graph import append_edge
    return append_edge(root, "override", f"slice:{slice_id}", f"module:{module_id}",
                       meta={"rule_ref": "gate:G6", "kind": "drift_ack",
                             "note": note})
