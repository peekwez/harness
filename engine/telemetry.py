"""Advisory telemetry aggregation feeding ``/harness:status``.

Telemetry must never block the workflow it observes. Buffered events use
stable IDs and an append-before-ack transfer so an interrupted flush can be
retried without either losing or double-counting an event.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

from . import append_jsonl, harness_dir, load_config, now_iso, read_jsonl


BUFFERED_KINDS = ("event", "slice_dispatched")


def _warn(action: str, exc: Exception) -> None:
    print(f"warning: telemetry {action} failed: {exc}", file=sys.stderr)


def _sync_file(path):
    if Path(path).exists():
        with open(path, "rb") as stream:
            os.fsync(stream.fileno())


def _sync_directory(path):
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _quarantine_bytes(root, source: str, raw: bytes, reason: str) -> None:
    """Durably preserve corrupt telemetry before its source is repaired."""
    hdir = harness_dir(root)
    hdir.mkdir(parents=True, exist_ok=True)
    path = hdir / "telemetry.quarantine.jsonl"
    digest = hashlib.sha256(source.encode("utf-8") + b"\0" + raw).hexdigest()
    row = {
        "id": f"quarantine:{digest}",
        "ts": now_iso(),
        "source": source,
        "reason": reason,
        "raw_base64": base64.b64encode(raw).decode("ascii"),
    }

    existing = read_jsonl(path) if path.exists() else []
    if any(item.get("id") == row["id"] for item in existing):
        _sync_file(path)
        _sync_directory(hdir)
        return

    # Atomic replacement keeps the diagnostic file valid if this process is
    # interrupted while recording evidence. Callers hold the sidecar write
    # lock, so telemetry repair and quarantine writers are serialized.
    prior = path.read_bytes() if path.exists() else b""
    if prior and not prior.endswith(b"\n"):
        prior += b"\n"
    encoded = (json.dumps(row, sort_keys=True, ensure_ascii=False)
               + "\n").encode("utf-8")
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "xb") as stream:
            stream.write(prior)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        _sync_file(path)
        _sync_directory(hdir)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _json_object(raw: bytes | str) -> dict:
    row = json.loads(raw)
    if not isinstance(row, dict):
        raise ValueError("telemetry row must be a JSON object")
    return row


def _repair_trailing_jsonl(root, path: Path, source: str) -> None:
    """Repair only a final unterminated row, preserving it in quarantine."""
    if not path.exists():
        return
    data = path.read_bytes()
    if not data or data.endswith(b"\n"):
        return

    boundary = data.rfind(b"\n")
    prefix = data[:boundary + 1] if boundary >= 0 else b""
    tail = data[boundary + 1:]
    # Refuse to reinterpret interior corruption as a crash tail.
    for line in prefix.splitlines():
        if line.strip():
            _json_object(line)

    try:
        _json_object(tail)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        _quarantine_bytes(root, source, tail, str(exc))
        with open(path, "r+b") as stream:
            stream.truncate(len(prefix))
            stream.flush()
            os.fsync(stream.fileno())
        _warn("recovery", exc)
    else:
        # A complete final row without a terminator would be concatenated with
        # the next O_APPEND write, so make the boundary explicit first.
        with open(path, "ab") as stream:
            stream.write(b"\n")
            stream.flush()
            os.fsync(stream.fileno())


def _legacy_id(source: str, position: int, row: dict) -> str:
    """Stable identity for rows written before telemetry IDs were introduced."""
    payload = json.dumps(row, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:20]
    return f"legacy:{source}:{position}:{digest}"


def _rows_from_file(path: Path, source: str) -> list:
    rows = read_jsonl(path)
    return [dict(row, id=row.get("id") or _legacy_id(source, i, row))
            for i, row in enumerate(rows)]


def _deduplicate(rows: list) -> list:
    out, seen = [], set()
    for row in rows:
        event_id = row.get("id")
        if event_id and event_id in seen:
            continue
        if event_id:
            seen.add(event_id)
        out.append(row)
    return out


def _tracked_rows(root) -> list:
    hdir = harness_dir(root)
    return _deduplicate(
        _rows_from_file(hdir / "telemetry.archive.jsonl", "archive")
        + _rows_from_file(hdir / "telemetry.jsonl", "live"))


def emit(root, kind: str, meta: dict, *, event_id=None, buffered=False) -> None:
    """Record one diagnostic event without blocking the observed workflow."""
    row = {"id": event_id or f"evt:{uuid.uuid4().hex}", "ts": now_iso(),
           "kind": kind, "meta": meta}
    from .events import Sidecar

    if buffered or kind in BUFFERED_KINDS:
        try:
            sidecar = Sidecar(root)
            try:
                sidecar.telemetry_buffer(row)
            finally:
                sidecar.close()
        except Exception as exc:  # diagnostic storage is best-effort
            try:
                append_jsonl(harness_dir(root) / "telemetry.jsonl", row)
            except Exception as fallback_exc:
                _warn("emit", fallback_exc)
            else:
                _warn("buffer", exc)
        return

    sidecar = None
    try:
        sidecar = Sidecar(root)
        sidecar.db.execute("BEGIN IMMEDIATE")
        try:
            live_path = harness_dir(root) / "telemetry.jsonl"
            _repair_trailing_jsonl(root, live_path, "telemetry.jsonl")
            append_jsonl(live_path, row)
            _sync_file(live_path)
        except Exception as exc:
            sidecar.db.execute("INSERT INTO telemetry_buffer(row) VALUES(?)",
                               (json.dumps(row, sort_keys=True),))
            sidecar.db.commit()
            _warn("emit", exc)
            return
        sidecar.db.commit()
    except Exception as exc:
        if sidecar is not None:
            try:
                sidecar.db.rollback()
            except Exception:
                pass
        try:
            append_jsonl(harness_dir(root) / "telemetry.jsonl", row)
        except Exception as fallback_exc:
            _warn("emit", fallback_exc)
        else:
            _warn("locking", exc)
    finally:
        if sidecar is not None:
            sidecar.close()


def flush(root) -> int:
    """Append selected rows, then acknowledge only their SQLite row IDs."""
    from .events import Sidecar

    sidecar = None
    try:
        sidecar = Sidecar(root)
        sidecar.db.execute("BEGIN IMMEDIATE")
        selected = sidecar.db.execute(
            "SELECT id, row FROM telemetry_buffer ORDER BY id").fetchall()
        if not selected:
            sidecar.db.commit()
            return 0

        hdir = harness_dir(root)
        _repair_trailing_jsonl(
            root, hdir / "telemetry.archive.jsonl",
            "telemetry.archive.jsonl")
        _repair_trailing_jsonl(
            root, hdir / "telemetry.jsonl", "telemetry.jsonl")
        existing = {row["id"] for row in _tracked_rows(root) if row.get("id")}
        selected_ids = []
        for buffer_id, raw in selected:
            try:
                row = _json_object(raw)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError,
                    TypeError) as exc:
                raw_bytes = (raw if isinstance(raw, bytes)
                             else str(raw).encode("utf-8", "surrogatepass"))
                try:
                    _quarantine_bytes(
                        root, f"telemetry_buffer:{buffer_id}", raw_bytes,
                        str(exc))
                except Exception as quarantine_exc:
                    _warn("quarantine", quarantine_exc)
                    continue
                _warn("buffer recovery", exc)
                selected_ids.append((buffer_id,))
                continue
            row = dict(row, id=row.get("id") or
                       _legacy_id("buffer", buffer_id, row))
            if row["id"] not in existing:
                append_jsonl(harness_dir(root) / "telemetry.jsonl", row)
                existing.add(row["id"])
            selected_ids.append((buffer_id,))

        # Acknowledgement must follow durable file data, not just a page-cache write.
        for name in ("telemetry.jsonl", "telemetry.archive.jsonl"):
            _sync_file(harness_dir(root) / name)
        sidecar.db.executemany(
            "DELETE FROM telemetry_buffer WHERE id=?", selected_ids)
        sidecar.db.commit()
        return len(selected_ids)
    except Exception as exc:
        if sidecar is not None:
            try:
                sidecar.db.rollback()
            except Exception:
                pass
        _warn("flush", exc)
        return 0
    finally:
        if sidecar is not None:
            sidecar.close()


def rotate(root, config=None) -> int:
    """Move old live rows to the archive without losing logical events."""
    from . import write_jsonl
    from .events import Sidecar

    sidecar = None
    try:
        cap = int(((config or {}).get("telemetry") or {}).get(
            "max_rows", 5000))
        if cap <= 0:
            return 0
        sidecar = Sidecar(root)
        sidecar.db.execute("BEGIN IMMEDIATE")
        hdir = harness_dir(root)
        live_path = hdir / "telemetry.jsonl"
        archive_path = hdir / "telemetry.archive.jsonl"
        _repair_trailing_jsonl(root, live_path, "telemetry.jsonl")
        _repair_trailing_jsonl(
            root, archive_path, "telemetry.archive.jsonl")
        live = _rows_from_file(live_path, "live")
        if len(live) <= cap:
            sidecar.db.commit()
            return 0

        moved, keep = live[:-cap], live[-cap:]
        archived_ids = {row["id"] for row in
                        _rows_from_file(archive_path, "archive")}
        for row in moved:
            if row["id"] not in archived_ids:
                append_jsonl(archive_path, row)
                archived_ids.add(row["id"])
        # Archive append precedes live acknowledgement. A failed rewrite is
        # retryable because the archived IDs are recognized on the next pass.
        _sync_file(archive_path)
        write_jsonl(live_path, keep)
        sidecar.db.commit()
        return len(moved)
    except Exception as exc:
        if sidecar is not None:
            try:
                sidecar.db.rollback()
            except Exception:
                pass
        _warn("rotation", exc)
        return 0
    finally:
        if sidecar is not None:
            sidecar.close()


def load(root) -> list:
    """Read archive, live file, and buffer as one deduplicated history."""
    rows = []
    hdir = harness_dir(root)
    for path, source in ((hdir / "telemetry.archive.jsonl", "archive"),
                         (hdir / "telemetry.jsonl", "live")):
        try:
            rows.extend(_rows_from_file(path, source))
        except Exception as exc:
            _warn("load", exc)

    from .events import Sidecar
    sidecar = None
    try:
        sidecar = Sidecar(root)
        for buffer_id, raw in sidecar.db.execute(
                "SELECT id, row FROM telemetry_buffer ORDER BY id").fetchall():
            try:
                row = _json_object(raw)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError,
                    TypeError) as exc:
                _warn("load", exc)
                continue
            rows.append(dict(row, id=row.get("id") or
                             _legacy_id("buffer", buffer_id, row)))
    except Exception as exc:
        _warn("load", exc)
    finally:
        if sidecar is not None:
            sidecar.close()
    return _deduplicate(rows)


def aggregate(root, since: str | None = None) -> dict:
    """Build a windowed dashboard with explicit samples and observation span."""
    config = load_config(root)
    rows = load(root)
    from .graph import load_edges
    edges = load_edges(root)
    if since:
        rows = [r for r in rows if str(r.get("ts", "")) >= since]
        edges = [e for e in edges if str(e.get("ts", "")) >= since]

    events = [r for r in rows if r.get("kind") == "event"]
    pre_changes = [r for r in events if r.get("meta", {}).get("event") ==
                   "pre_change"]
    g2_blocks = [r for r in pre_changes
                 if r.get("meta", {}).get("verdict") == "block"
                 and "gate:G2" in r.get("meta", {}).get("gates", [])]

    overrides: dict = {}
    reversals: dict = {}
    for edge in edges:
        if edge.get("type") == "override":
            rule = edge.get("meta", {}).get("rule_ref", "unknown")
            overrides[rule] = overrides.get(rule, 0) + 1
            if edge.get("meta", {}).get("reverses"):
                reversals[rule] = reversals.get(rule, 0) + 1
        if (edge.get("type") == "decided_by"
                and edge.get("meta", {}).get("reverses")):
            reversals["adjudication"] = reversals.get("adjudication", 0) + 1

    parks_per_slice: dict = {}
    for row in rows:
        if row.get("kind") not in ("park", "slice_parked"):
            continue
        slice_id = row.get("meta", {}).get("slice", "unknown")
        parks_per_slice[slice_id] = parks_per_slice.get(slice_id, 0) + 1

    compactions = [r for r in rows if r.get("kind") == "COMPACTION_REACHED"]
    slices = {"planned": 0, "in_progress": 0, "parked": 0, "closed": 0}
    from . import SubstrateMissing, load_backlog
    try:
        backlog = load_backlog(root)
    except SubstrateMissing:
        backlog = []
    for row in backlog:
        status = row.get("status", "planned")
        slices[status] = slices.get(status, 0) + 1

    fired: dict = {}
    for row in events:
        for rule in row.get("meta", {}).get("gates", []):
            fired[rule] = fired.get(rule, 0) + 1
    rule_samples = {
        rule: {"firings": fired.get(rule, 0),
               "overrides": overrides.get(rule, 0),
               "reversals": reversals.get(rule, 0)}
        for rule in sorted(set(fired) | set(overrides) | set(reversals))
    }

    outcome_counts = {
        "slice_dispatched": 0, "slice_closed": 0, "slice_merged": 0,
        "slice_parked": 0, "review_parked": 0,
        "event_allow": 0, "event_allow_with_findings": 0, "event_block": 0,
    }
    for row in rows:
        kind = row.get("kind")
        if kind in ("slice_dispatched", "slice_closed", "slice_merged",
                    "slice_parked"):
            outcome_counts[kind] += 1
        elif kind == "park":
            outcome_counts["review_parked"] += 1
        elif kind == "event":
            key = f"event_{row.get('meta', {}).get('verdict')}"
            if key in outcome_counts:
                outcome_counts[key] += 1

    timestamps = sorted(
        str(item.get("ts")) for item in [*rows, *edges] if item.get("ts"))
    observed_interval = {
        "start": timestamps[0] if timestamps else None,
        "end": timestamps[-1] if timestamps else None,
    }
    sample_counts = {
        "telemetry_rows": len(rows), "events": len(events),
        "pre_change_events": len(pre_changes), "graph_edges": len(edges),
    }
    window = ({"since": since, "rows": len(rows), "edges": len(edges)}
              if since else None)

    return {
        "slices": slices,
        "window": window,
        "sample_counts": sample_counts,
        "observed_interval": observed_interval,
        "pre_change_events": len(pre_changes),
        "g2_block_rate": (len(g2_blocks) / len(pre_changes)) if pre_changes else 0.0,
        "override_counts": overrides,
        "reversal_counts": reversals,
        "rule_samples": rule_samples,
        "layer0_promotion_candidates": [],
        "outcome_counts": outcome_counts,
        "compaction_reached": len(compactions),
        "compaction_is_defect": bool(
            (config.get("telemetry") or {}).get("compaction_is_defect", False)),
        "parks_per_slice": parks_per_slice,
    }
