"""Telemetry: event aggregation feeding /harness:status.

G2-block rate (Phase-1 completeness), override/reversal rates per rule
(zero-variance rules are Layer-0 promotion candidates), COMPACTION_REACHED
(decomposition-quality defect signal), parks per slice.
"""
from __future__ import annotations

from . import append_jsonl, harness_dir, now_iso, read_jsonl


# Hook-frequency events buffer in the gitignored sidecar and flush once at
# close: appending every one to the tracked file forced "session churn"
# commits before every merge (review R8). Ceremony-level events (close,
# merge, park, compaction) are milestones — they land immediately.
BUFFERED_KINDS = ("event", "slice_dispatched")


def emit(root, kind: str, meta: dict) -> None:
    row = {"ts": now_iso(), "kind": kind, "meta": meta}
    if kind in BUFFERED_KINDS:
        from .events import Sidecar
        sidecar = Sidecar(root)
        try:
            sidecar.telemetry_buffer(row)
            return
        finally:
            sidecar.close()
    append_jsonl(harness_dir(root) / "telemetry.jsonl", row)


def flush(root) -> int:
    """Move buffered rows into the tracked file (close-slice / merge-slice).
    Returns the number of rows flushed."""
    from .events import Sidecar
    sidecar = Sidecar(root)
    try:
        rows = sidecar.telemetry_drain()
    finally:
        sidecar.close()
    for row in rows:
        append_jsonl(harness_dir(root) / "telemetry.jsonl", row)
    return len(rows)


def rotate(root, config=None) -> int:
    """Keep the tracked file bounded: rows beyond `telemetry.max_rows` move
    to telemetry.archive.jsonl (append-only, union-merged like the live
    file). Nothing is deleted — history stays, diffs stay small. Returns the
    number of rows moved."""
    from . import write_jsonl
    cap = int(((config or {}).get("telemetry") or {}).get("max_rows", 5000))
    path = harness_dir(root) / "telemetry.jsonl"
    rows = read_jsonl(path)
    if cap <= 0 or len(rows) <= cap:
        return 0
    keep = rows[-cap:]
    for row in rows[:-cap]:
        append_jsonl(harness_dir(root) / "telemetry.archive.jsonl", row)
    write_jsonl(path, keep)
    return len(rows) - cap


def load(root) -> list:
    """Tracked rows plus anything still buffered — the dashboard must never
    under-report just because a slice hasn't closed yet."""
    rows = read_jsonl(harness_dir(root) / "telemetry.jsonl")
    from .events import Sidecar
    sidecar = Sidecar(root)
    try:
        rows += sidecar.telemetry_peek()
    finally:
        sidecar.close()
    return rows


def aggregate(root, since: str | None = None) -> dict:
    rows = load(root)
    window = None
    if since:
        rows = [r for r in rows if str(r.get("ts", "")) >= since]
        window = {"since": since, "rows": len(rows)}
    events = [r for r in rows if r["kind"] == "event"]
    pre_changes = [r for r in events if r["meta"].get("event") == "pre_change"]
    g2_blocks = [r for r in pre_changes
                 if r["meta"].get("verdict") == "block"
                 and "gate:G2" in r["meta"].get("gates", [])]

    overrides: dict = {}
    reversals: dict = {}
    from .graph import load_edges
    # corrupt edges.jsonl must fail loud here, not zero out the dashboard
    for e in load_edges(root):
        if e["type"] == "override":
            rule = e.get("meta", {}).get("rule_ref", "unknown")
            overrides[rule] = overrides.get(rule, 0) + 1
            if e.get("meta", {}).get("reverses"):
                reversals[rule] = reversals.get(rule, 0) + 1
        if e["type"] == "decided_by" and e.get("meta", {}).get("reverses"):
            rule = "adjudication"
            reversals[rule] = reversals.get(rule, 0) + 1

    parks = [r for r in rows if r["kind"] == "park"]
    parks_per_slice: dict = {}
    for p in parks:
        s = p["meta"].get("slice", "unknown")
        parks_per_slice[s] = parks_per_slice.get(s, 0) + 1

    compactions = [r for r in rows if r["kind"] == "COMPACTION_REACHED"]

    slices = {"planned": 0, "in_progress": 0, "parked": 0, "closed": 0}
    from . import SubstrateMissing, load_backlog
    try:
        backlog = load_backlog(root)
    except SubstrateMissing:
        backlog = []  # legal pre-Phase-0; corruption still raises
    for s in backlog:
        st = s.get("status", "planned")
        slices[st] = slices.get(st, 0) + 1

    # Promotion candidates answer "which rules are stable enough to become
    # Layer-0 checks?" — so the denominator is rules that FIRED, not only
    # ones that were overridden (the old form could only ever nominate a
    # rule someone had overridden, i.e. the opposite signal; review R7).
    fired: dict = {}
    for r in events:
        for rule in r["meta"].get("gates", []):
            fired[rule] = fired.get(rule, 0) + 1
    promotion_candidates = sorted(
        rule for rule, n in fired.items()
        if n >= 1 and overrides.get(rule, 0) == 0 and reversals.get(rule, 0) == 0)

    return {
        "slices": slices,
        "window": window,
        "pre_change_events": len(pre_changes),
        "g2_block_rate": (len(g2_blocks) / len(pre_changes)) if pre_changes else 0.0,
        "override_counts": overrides,
        "reversal_counts": reversals,
        "layer0_promotion_candidates": promotion_candidates,
        "compaction_reached": len(compactions),
        "compaction_is_defect": True,
        "parks_per_slice": parks_per_slice,
    }
