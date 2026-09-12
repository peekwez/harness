"""Regression coverage for durable, advisory telemetry."""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor

from engine import read_jsonl, write_jsonl
from engine.events import Sidecar


def _event(ts, event_id, *, verdict="allow", gates=None):
    return {
        "id": event_id,
        "ts": ts,
        "kind": "event",
        "meta": {
            "event": "pre_change",
            "session": "s",
            "slice": "slice-042",
            "verdict": verdict,
            "codes": [],
            "gates": gates or [],
        },
    }


def test_flush_retries_after_partial_append_without_loss_or_duplicates(
        toy, monkeypatch, capsys):
    """A write failure must leave selected buffer rows retryable by ID."""
    from engine import telemetry

    telemetry.emit(toy, "event", {"event": "pre_change", "verdict": "allow"})
    telemetry.emit(toy, "event", {"event": "pre_change", "verdict": "block"})
    original = telemetry.append_jsonl
    calls = 0

    def fail_second(path, row):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk full")
        original(path, row)

    monkeypatch.setattr(telemetry, "append_jsonl", fail_second)
    assert telemetry.flush(toy) == 0
    assert "warning: telemetry flush failed" in capsys.readouterr().err
    sidecar = Sidecar(toy)
    try:
        assert len(sidecar.telemetry_peek()) == 2
    finally:
        sidecar.close()

    monkeypatch.setattr(telemetry, "append_jsonl", original)
    assert telemetry.flush(toy) == 2
    events = [r for r in read_jsonl(toy / ".harness" / "telemetry.jsonl")
              if r["kind"] == "event"]
    assert len(events) == 2
    assert len({r["id"] for r in events}) == 2


def test_concurrent_flushes_acknowledge_each_buffer_row_once(toy):
    """Two flushers must not duplicate or delete one another's selections."""
    from engine import telemetry

    for i in range(20):
        telemetry.emit(toy, "event", {"event": "pre_change", "sequence": i})
    with ThreadPoolExecutor(max_workers=2) as pool:
        counts = list(pool.map(lambda _: telemetry.flush(toy), range(2)))
    rows = [r for r in read_jsonl(toy / ".harness" / "telemetry.jsonl")
            if r["kind"] == "event"]
    assert sum(counts) == 20
    assert len(rows) == 20
    assert len({r["id"] for r in rows}) == 20


def test_load_combines_archive_live_and_buffer_and_deduplicates_ids(toy):
    """Rotation or flush retry overlap must remain one logical event."""
    from engine import telemetry

    old = _event("2026-01-01T00:00:00+00:00", "event-old")
    current = _event("2026-01-02T00:00:00+00:00", "event-current")
    buffered = _event("2026-01-03T00:00:00+00:00", "event-buffered")
    write_jsonl(toy / ".harness" / "telemetry.archive.jsonl", [old, current])
    write_jsonl(toy / ".harness" / "telemetry.jsonl", [current, buffered])
    sidecar = Sidecar(toy)
    try:
        sidecar.telemetry_buffer(buffered)
    finally:
        sidecar.close()

    rows = telemetry.load(toy)
    assert [r["id"] for r in rows] == ["event-old", "event-current",
                                       "event-buffered"]


def test_failed_direct_emit_is_advisory_and_buffered_for_retry(
        toy, monkeypatch, capsys):
    """Optional logging failure must not block work or discard the event."""
    from engine import telemetry

    original = telemetry.append_jsonl
    monkeypatch.setattr(
        telemetry, "append_jsonl",
        lambda path, row: (_ for _ in ()).throw(OSError("read-only disk")))
    assert telemetry.emit(toy, "slice_closed", {"slice": "slice-042"}) is None
    assert "warning: telemetry emit failed" in capsys.readouterr().err

    monkeypatch.setattr(telemetry, "append_jsonl", original)
    assert telemetry.flush(toy) == 1
    assert sum(r["kind"] == "slice_closed" for r in telemetry.load(toy)) == 1


def test_aggregate_applies_since_to_events_and_edges_and_reports_samples(toy):
    """Windowed rates must not mix recent events with lifetime graph edges."""
    from engine import telemetry

    write_jsonl(toy / ".harness" / "telemetry.jsonl", [
        _event("2020-01-01T00:00:00+00:00", "old-event", verdict="block",
               gates=["gate:G2"]),
        _event("2026-01-02T00:00:00+00:00", "new-event", verdict="allow"),
    ])
    write_jsonl(toy / ".harness" / "edges.jsonl", [
        {"ts": "2020-01-01T00:00:00+00:00", "type": "override",
         "from": "slice:x", "to": "module:x", "commit": None,
         "meta": {"rule_ref": "gate:G2"}},
        {"ts": "2026-01-03T00:00:00+00:00", "type": "override",
         "from": "slice:y", "to": "module:y", "commit": None,
         "meta": {"rule_ref": "gate:G5"}},
    ])

    out = telemetry.aggregate(toy, since="2026-01-01")
    assert out["override_counts"] == {"gate:G5": 1}
    assert out["sample_counts"] == {
        "telemetry_rows": 1, "events": 1, "pre_change_events": 1,
        "graph_edges": 1,
    }
    assert out["observed_interval"] == {
        "start": "2026-01-02T00:00:00+00:00",
        "end": "2026-01-03T00:00:00+00:00",
    }


def test_aggregate_exposes_retry_parks_outcomes_and_advisory_compaction(toy):
    """Status must report automatic parks without claiming one-shot promotion."""
    from engine import telemetry
    import yaml

    cfg_path = toy / ".harness" / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg.setdefault("telemetry", {})["compaction_is_defect"] = False
    cfg_path.write_text(yaml.safe_dump(cfg))

    telemetry.emit(toy, "slice_parked", {"slice": "slice-042", "attempts": 3})
    telemetry.emit(toy, "slice_closed", {"slice": "slice-099"})
    telemetry.emit(toy, "COMPACTION_REACHED", {"slice": "slice-042"})
    telemetry.emit(toy, "event", {"event": "unit_complete", "verdict": "block",
                                  "gates": ["gate:G3"], "codes": []})

    out = telemetry.aggregate(toy)
    assert out["parks_per_slice"] == {"slice-042": 1}
    assert out["outcome_counts"]["slice_parked"] == 1
    assert out["outcome_counts"]["slice_closed"] == 1
    assert out["outcome_counts"]["event_block"] == 1
    assert out["compaction_reached"] == 1
    assert out["compaction_is_defect"] is False
    assert out["layer0_promotion_candidates"] == []
def test_flush_retains_outbox_until_file_is_durable(toy, monkeypatch):
    from engine import telemetry
    from engine.events import Sidecar
    telemetry.emit(toy, "event", {"sample": "durability"})
    def fail_sync(_path):
        raise OSError("simulated fsync failure")
    with monkeypatch.context() as patch:
        patch.setattr(telemetry, "_sync_file", fail_sync)
        assert telemetry.flush(toy) == 0
    sidecar = Sidecar(toy)
    try:
        assert len(sidecar.telemetry_peek()) == 1
    finally:
        sidecar.close()
    assert telemetry.flush(toy) == 1
    assert len([r for r in telemetry.load(toy) if r["meta"].get("sample") == "durability"]) == 1


def test_flush_repairs_torn_live_tail_without_losing_valid_prefix(toy):
    """A crashed final append must not permanently poison outbox retries."""
    from engine import telemetry

    live = toy / ".harness" / "telemetry.jsonl"
    prefix = _event("2026-01-01T00:00:00+00:00", "complete")
    write_jsonl(live, [prefix])
    torn = b'{"id":"torn"'
    with open(live, "ab") as stream:
        stream.write(torn)
    telemetry.emit(toy, "event", {"event": "after-torn-tail"})

    assert telemetry.flush(toy) == 1
    rows = read_jsonl(live)
    assert rows[0] == prefix
    assert any(r["meta"].get("event") == "after-torn-tail" for r in rows)
    quarantine = read_jsonl(toy / ".harness" /
                            "telemetry.quarantine.jsonl")
    assert len(quarantine) == 1
    assert quarantine[0]["source"] == "telemetry.jsonl"
    assert base64.b64decode(quarantine[0]["raw_base64"]) == torn

    assert telemetry.flush(toy) == 0
    assert len(read_jsonl(toy / ".harness" /
                          "telemetry.quarantine.jsonl")) == 1


def test_direct_emit_separates_a_valid_unterminated_final_row(toy):
    """A complete legacy final row needs a newline before the next append."""
    from engine import telemetry

    live = toy / ".harness" / "telemetry.jsonl"
    prior = _event("2026-01-01T00:00:00+00:00", "unterminated")
    write_jsonl(live, [prior])
    live.write_bytes(live.read_bytes().removesuffix(b"\n"))

    telemetry.emit(toy, "slice_closed", {"slice": "slice-042"})

    rows = read_jsonl(live)
    assert rows[0] == prior
    assert rows[1]["kind"] == "slice_closed"
    assert not (toy / ".harness" / "telemetry.quarantine.jsonl").exists()


def test_malformed_buffer_row_is_quarantined_without_stranding_valid_rows(toy):
    """Corrupt optional telemetry must not hide or block later valid events."""
    from engine import telemetry

    raw = "{bad"
    sidecar = Sidecar(toy)
    try:
        sidecar.db.execute(
            "INSERT INTO telemetry_buffer(row) VALUES(?)", (raw,))
        sidecar.db.commit()
    finally:
        sidecar.close()
    telemetry.emit(toy, "event", {"event": "after-corrupt-buffer"})

    assert any(r["meta"].get("event") == "after-corrupt-buffer"
               for r in telemetry.load(toy))
    assert telemetry.flush(toy) == 2
    sidecar = Sidecar(toy)
    try:
        assert sidecar.telemetry_peek() == []
    finally:
        sidecar.close()
    assert any(r["meta"].get("event") == "after-corrupt-buffer"
               for r in telemetry.load(toy))
    quarantine = read_jsonl(toy / ".harness" /
                            "telemetry.quarantine.jsonl")
    assert len(quarantine) == 1
    assert quarantine[0]["source"].startswith("telemetry_buffer:")
    assert base64.b64decode(quarantine[0]["raw_base64"]).decode() == raw


def test_malformed_rotation_limit_is_advisory(toy, capsys):
    """Invalid optional telemetry config must not block close workflows."""
    from engine import telemetry

    assert telemetry.rotate(
        toy, {"telemetry": {"max_rows": "not-a-number"}}) == 0
    assert "warning: telemetry rotation failed" in capsys.readouterr().err
