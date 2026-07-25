"""G6 interface-drift: public-symbol shadow diff since slice start.

Blocks unit_complete until acknowledged; the ack is recorded as an edge.
"""
from __future__ import annotations

from ..events import make_finding
from ..registry import public_symbols

GATE = {"id": "G6", "rule_ref": "gate:G6",
        "preferred": ("unit_complete",), "fallback": ()}


def _shadow_source_hash(root, entry):
    import json
    from pathlib import Path
    sp = Path(root) / (entry.get("shadow") or "")
    try:
        return json.loads(sp.read_text()).get("source_hash")
    except (OSError, json.JSONDecodeError):
        return None


def _acked(ctx) -> set:
    from ..graph import load_edges
    s = f"slice:{ctx.work_unit_id}"
    return {e["to"] for e in load_edges(ctx.root)
            if e["from"] == s and e["type"] == "override"
            and e.get("meta", {}).get("rule_ref") == "gate:G6"}


def check(ctx) -> list:
    if not ctx.work_unit_id:
        return []
    baseline = ctx.sidecar.snapshot_get(ctx.work_unit_id)
    if not baseline:
        return []
    findings = []
    acked = _acked(ctx)
    registry = {e["id"]: e for e in ctx.registry}
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
        new_syms = public_symbols(ctx.root, entry)
        if new_syms is None or new_syms == old_syms:
            continue
        # symbols changed but source bytes did not: extractor version skew,
        # not interface drift — the ack ledger stays clean (W8)
        cur_hash = _shadow_source_hash(ctx.root, entry)
        if old.get("source_hash") and cur_hash == old["source_hash"]:
            continue
        if f"module:{module_id}" in acked:
            continue
        added = sorted(set(new_syms) - set(old_syms))
        removed = sorted(set(old_syms) - set(new_syms))
        findings.append(make_finding(
            "INTERFACE_DRIFT", GATE["rule_ref"],
            f"public interface of {module_id!r} drifted since slice start "
            f"(+{len(added)}/-{len(removed)}): added {added[:5]}, removed "
            f"{removed[:5]}; acknowledge with `harness gates ack-drift "
            f"--slice {ctx.work_unit_id} --module {module_id}`",
            severity="block", key=ctx.work_unit_id + "|" + module_id))
    return findings


def acknowledge(root, slice_id: str, module_id: str, note: str = "") -> dict:
    from ..graph import append_edge
    return append_edge(root, "override", f"slice:{slice_id}", f"module:{module_id}",
                       meta={"rule_ref": "gate:G6", "kind": "drift_ack",
                             "note": note})
