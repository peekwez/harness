"""Advisory telemetry (D-0.10-11).

Two files, one job each:

* `.harness/cache/events.jsonl` holds one row per event. It is local and
  gitignored. Hooks append to it. Nothing in CI reads it.
* `.harness/slice-metrics.jsonl` holds one committed row per closed slice.
  `close-slice` writes it with `record_slice_summary`. `harness status`
  reads it.

Telemetry never blocks the workflow it observes: a failed write prints a
warning and returns.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import append_jsonl, harness_dir, now_iso, read_jsonl, write_jsonl

EVENTS_PATH = ".harness/cache/events.jsonl"
METRICS_FILE = "slice-metrics.jsonl"


def _warn(action: str, exc: Exception) -> None:
    print(f"warning: telemetry {action} failed: {exc}", file=sys.stderr)


def emit(root, kind: str, meta: dict) -> None:
    """Append one local event row. Never raises."""
    row = {"ts": now_iso(), "kind": kind, "meta": dict(meta or {})}
    try:
        append_jsonl(Path(root) / EVENTS_PATH, row)
    except Exception as exc:  # noqa: BLE001 - telemetry never blocks
        _warn("emit", exc)


def load_events(root) -> list:
    """Local event rows. A torn or non-object line is skipped, not repaired:
    the file is a cache, and the committed record is the slice summary."""
    path = Path(root) / EVENTS_PATH
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        _warn("load", exc)
        return []
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def override_counts(edges, slice_id=None) -> dict:
    """Override edges per rule ref. An upgrade alias (`legacy_override`)
    preserves an old approval; it is not a new override."""
    counts: dict = {}
    for edge in edges:
        if edge.get("type") != "override":
            continue
        meta = edge.get("meta") or {}
        if meta.get("legacy_override"):
            continue
        if slice_id is not None and edge.get("from") != f"slice:{slice_id}":
            continue
        rule = meta.get("rule_ref") or "unknown"
        counts[rule] = counts.get(rule, 0) + 1
    return dict(sorted(counts.items()))


def reversal_counts(edges, slice_id=None, findings=None) -> dict:
    """Reversed overrides per rule ref, plus reversed adjudications under
    `adjudication`. Alias edges are skipped, as in `override_counts`. With a
    slice, an adjudication counts when its edge meta names that slice, or
    (older edges without one) when its finding is in `findings`, the finding
    ids the slice parked."""
    counts: dict = {}
    for edge in edges:
        meta = edge.get("meta") or {}
        if not meta.get("reverses") or meta.get("legacy_override"):
            continue
        kind = edge.get("type")
        if kind == "override":
            if slice_id is not None and edge.get("from") != f"slice:{slice_id}":
                continue
            rule = meta.get("rule_ref") or "unknown"
        elif kind == "decided_by":
            if slice_id is not None:
                owner = meta.get("slice")
                if owner is not None:
                    if owner != slice_id:
                        continue
                elif edge.get("from") not in {
                        f"finding:{f}" for f in findings or ()}:
                    continue
            rule = "adjudication"
        else:
            continue
        counts[rule] = counts.get(rule, 0) + 1
    return dict(sorted(counts.items()))


def summarize(slice_id: str, events: list, edges: list) -> dict:
    """The summary row for one slice from event rows and graph edges."""
    fired: dict = {}
    injection = compactions = parks = 0
    parked_findings = set()
    for row in events:
        meta = row.get("meta") or {}
        if meta.get("slice") != slice_id:
            continue
        kind = row.get("kind")
        if kind == "event":
            for rule in meta.get("gates") or []:
                fired[rule] = fired.get(rule, 0) + 1
            try:
                injection = max(injection, int(meta.get("injection_chars") or 0))
            except (TypeError, ValueError):
                pass
        elif kind == "COMPACTION_REACHED":
            compactions += 1
        elif kind in ("park", "slice_parked"):
            parks += 1
            if meta.get("finding_id"):
                parked_findings.add(meta["finding_id"])
    return {"id": slice_id, "gates_fired": dict(sorted(fired.items())),
            "overrides": override_counts(edges, slice_id),
            "reversals": reversal_counts(edges, slice_id, parked_findings),
            "max_injection_chars": injection, "compactions": compactions,
            "parks": parks}


def load_summaries(root) -> list:
    """Committed summary rows. A malformed file fails loud (it is substrate)."""
    return read_jsonl(harness_dir(root) / METRICS_FILE)


def write_summary(root, row: dict) -> None:
    """Upsert one row by `id`. One row per slice, sorted by id."""
    path = harness_dir(root) / METRICS_FILE
    rows = [r for r in read_jsonl(path) if r.get("id") != row["id"]]
    rows.append(row)
    write_jsonl(path, sorted(rows, key=lambda r: str(r.get("id"))))


def record_slice_summary(root, slice_id, extra=None) -> dict:
    """Write the slice's committed summary row at close (D-0.10-11).

    Args:
        root: Substrate root.
        slice_id: The slice being closed.
        extra: Fields other workstreams add (W5: red_before_green,
            green_at_start; W6: explore_skipped).

    Returns:
        The row written.
    """
    from .graph import load_edges
    row = summarize(slice_id, load_events(root), load_edges(root))
    row.update({"closed_at": now_iso(), "source": "close"})
    if extra:
        row.update(extra)
    row["id"] = slice_id
    write_summary(root, row)
    return row


def status(root, since=None) -> dict:
    """The `harness status` report: slice counts plus summary totals."""
    from . import SubstrateMissing, load_backlog
    try:
        backlog = load_backlog(root)
    except SubstrateMissing:
        backlog = []
    slices = {"planned": 0, "in_progress": 0, "parked": 0, "closed": 0}
    for row in backlog:
        state = row.get("status", "planned")
        slices[state] = slices.get(state, 0) + 1
    summaries = load_summaries(root)
    if since:
        summaries = [r for r in summaries if str(r.get("closed_at", "")) >= since]
    totals = {"gates_fired": {}, "overrides": {}, "reversals": {},
              "compactions": 0,
              "parks": 0, "max_injection_chars": 0}
    for row in summaries:
        for key in ("gates_fired", "overrides", "reversals"):
            for rule, n in (row.get(key) or {}).items():
                totals[key][rule] = totals[key].get(rule, 0) + int(n)
        totals["compactions"] += int(row.get("compactions") or 0)
        totals["parks"] += int(row.get("parks") or 0)
        totals["max_injection_chars"] = max(
            totals["max_injection_chars"], int(row.get("max_injection_chars") or 0))
    for key in ("gates_fired", "overrides", "reversals"):
        totals[key] = dict(sorted(totals[key].items()))
    parks_per_slice = {r["id"]: int(r["parks"]) for r in summaries if r.get("parks")}
    for row in read_jsonl(harness_dir(root) / "parked.jsonl"):
        sid = row.get("slice", "unknown")
        parks_per_slice[sid] = parks_per_slice.get(sid, 0) + 1
    return {"slices": slices,
            "window": {"since": since, "summaries": len(summaries)} if since else None,
            "summaries": summaries, "totals": totals,
            "parks_per_slice": parks_per_slice,
            "local_events": len(load_events(root))}
