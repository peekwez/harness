"""D-0.10-11: per-event rows stay local; close commits one summary row per
slice to .harness/slice-metrics.jsonl; status reads summaries."""
import json

from conftest import git, make_event, run_cli
from engine import read_jsonl, write_jsonl
from engine.events import handle_event

GOOD_ORDERS = ("import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
               "    telemetry.emit_span('create_order', {'sku': sku})\n"
               "    return {'sku': sku}\n")
EVENTS = (".harness", "cache", "events.jsonl")


def _events(toy):
    return read_jsonl(toy.joinpath(*EVENTS))


def _metrics(toy):
    return read_jsonl(toy / ".harness" / "slice-metrics.jsonl")


def _commit_green_slice(toy, session):
    run_cli("slice", "--slice", "slice-042", "--session", session, root=toy)
    (toy / "orders.py").write_text(GOOD_ORDERS)
    handle_event(make_event("post_change", session=session,
                            files=["orders.py"]), toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "slice-042: orders")


def _close(toy, session):
    return run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)


def test_emit_appends_to_the_local_events_file(toy):
    from engine import telemetry
    telemetry.emit(toy, "slice_parked", {"slice": "slice-042"})
    row = _events(toy)[-1]
    assert row["kind"] == "slice_parked"
    assert row["meta"] == {"slice": "slice-042"} and row["ts"]
    assert not (toy / ".harness" / "telemetry.jsonl").exists()


def test_hook_events_never_touch_tracked_files(toy):
    v = handle_event(make_event("pre_change", session="quiet",
                                files=["orders.py"]), toy)
    rows = [r for r in _events(toy) if r["kind"] == "event"]
    assert rows and "injection_chars" in rows[-1]["meta"]
    assert rows[-1]["meta"]["verdict"] == v["verdict"]
    assert git(toy, "status", "--porcelain", "--", ".harness").stdout == ""


def test_emit_failure_never_raises(toy, capsys):
    from engine import telemetry
    toy.joinpath(*EVENTS).mkdir(parents=True)   # a directory blocks the file
    assert telemetry.emit(toy, "event", {"slice": "slice-042"}) is None
    assert "telemetry emit failed" in capsys.readouterr().err


def test_load_events_skips_a_torn_line(toy):
    from engine import telemetry
    telemetry.emit(toy, "event", {"slice": "slice-042", "gates": ["gate:G3"]})
    with toy.joinpath(*EVENTS).open("a") as fh:
        fh.write('{"ts": "2026-10-02T00:00:00+00:00", "kind": "ev')
    assert len(telemetry.load_events(toy)) == 1
    row = telemetry.record_slice_summary(toy, "slice-042")
    assert row["gates_fired"] == {"gate:G3": 1}
    proc = run_cli("status", root=toy)
    assert proc.returncode == 0, proc.stderr


def test_summary_counts_gates_injection_compactions_parks_overrides(toy):
    from engine import telemetry
    from engine.gates.g5_conformance import record_override
    for chars in (1200, 8700):
        telemetry.emit(toy, "event", {"slice": "slice-042",
                                      "gates": ["gate:G3"],
                                      "injection_chars": chars})
    telemetry.emit(toy, "event", {"slice": "other", "gates": ["gate:G5"]})
    telemetry.emit(toy, "COMPACTION_REACHED", {"slice": "slice-042"})
    telemetry.emit(toy, "park", {"slice": "slice-042", "finding_id": "F-1"})
    record_override(toy, "slice-042", "file:rogue.py", "agreed in review",
                    rule_ref="gate:G3")
    row = telemetry.record_slice_summary(toy, "slice-042",
                                         extra={"red_before_green": True})
    assert row["gates_fired"] == {"gate:G3": 2}
    assert row["max_injection_chars"] == 8700
    assert row["compactions"] == 1 and row["parks"] == 1
    assert row["overrides"] == {"gate:G3": 1}
    assert row["red_before_green"] is True
    assert row["id"] == "slice-042" and row["source"] == "close"
    assert row["closed_at"]
    assert _metrics(toy) == [row]


def test_summary_is_one_row_per_slice(toy):
    from engine import telemetry
    telemetry.record_slice_summary(toy, "slice-042")
    telemetry.record_slice_summary(toy, "slice-042", extra={"note": "again"})
    rows = _metrics(toy)
    assert [r["id"] for r in rows] == ["slice-042"]
    assert rows[0]["note"] == "again"


def test_close_commits_the_summary_and_no_event_rows(toy):
    _commit_green_slice(toy, "tel-close")
    proc = _close(toy, "tel-close")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["slice_metrics"]["id"] == "slice-042"
    assert "telemetry_flushed" not in out
    committed = git(toy, "show", "HEAD:.harness/slice-metrics.jsonl").stdout
    assert json.loads(committed.splitlines()[0])["id"] == "slice-042"
    assert git(toy, "ls-files", ".harness/cache").stdout.strip() == ""


def test_retried_close_writes_one_summary_row(toy):
    """Review Focus 4: rollback restores the file; the retry writes once."""
    _commit_green_slice(toy, "tel-retry")
    hook = toy / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    assert _close(toy, "tel-retry").returncode == 1
    assert not [r for r in _metrics(toy) if r["id"] == "slice-042"]
    hook.unlink()
    proc = _close(toy, "tel-retry")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert [r["id"] for r in _metrics(toy)] == ["slice-042"]


def test_status_reads_summaries_and_filters_by_since(toy):
    write_jsonl(toy / ".harness" / "slice-metrics.jsonl", [
        {"id": "new", "closed_at": "2026-09-30T00:00:00+00:00",
         "gates_fired": {"gate:G3": 1, "gate:G6": 1},
         "overrides": {"gate:G3": 1}, "max_injection_chars": 900,
         "compactions": 0, "parks": 1, "source": "close"},
        {"id": "old", "closed_at": "2020-01-01T00:00:00+00:00",
         "gates_fired": {"gate:G3": 4}, "overrides": {},
         "max_injection_chars": 100, "compactions": 2, "parks": 0,
         "source": "close"}])
    out = json.loads(run_cli("status", root=toy).stdout)
    assert out["totals"]["gates_fired"] == {"gate:G3": 5, "gate:G6": 1}
    assert out["totals"]["overrides"] == {"gate:G3": 1}
    assert out["totals"]["compactions"] == 2
    assert out["totals"]["max_injection_chars"] == 900
    assert out["parks_per_slice"] == {"new": 1}
    assert "compaction_is_defect" not in json.dumps(out)
    windowed = json.loads(run_cli("status", "--since", "2021-01-01",
                                  root=toy).stdout)
    assert [r["id"] for r in windowed["summaries"]] == ["new"]
    assert windowed["window"] == {"since": "2021-01-01", "summaries": 1}


def test_sidecar_has_no_telemetry_buffer(toy):
    from engine.events import Sidecar
    sc = Sidecar(toy)
    try:
        assert not hasattr(sc, "telemetry_buffer")
        assert sc.db.execute("SELECT name FROM sqlite_master WHERE "
                             "name='telemetry_buffer'").fetchone() is None
    finally:
        sc.close()


def test_verify_rejects_duplicate_summary_rows(toy):
    row = {"id": "slice-042", "closed_at": "2026-10-01T00:00:00+00:00"}
    write_jsonl(toy / ".harness" / "slice-metrics.jsonl", [row, row])
    proc = run_cli("verify", root=toy)
    assert proc.returncode == 1
    assert "slice-metrics.jsonl: duplicate id" in proc.stdout


def test_init_scaffolds_metrics_and_keyed_merge(tmp_path):
    root = tmp_path / "fresh"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n")
    git(root, "init", "-q")
    assert run_cli("init", root=root).returncode == 0
    assert (root / ".harness" / "slice-metrics.jsonl").exists()
    assert not (root / ".harness" / "telemetry.jsonl").exists()
    ga = (root / ".gitattributes").read_text()
    assert ".harness/slice-metrics.jsonl merge=harness-substrate" in ga
    assert "telemetry.jsonl" not in ga


def test_summary_counts_reversals(toy):
    from engine import telemetry
    edges = [
        {"type": "override", "from": "slice:slice-042", "to": "file:a",
         "meta": {"rule_ref": "gate:G3", "reverses": True}},
        {"type": "override", "from": "slice:slice-042", "to": "file:b",
         "meta": {"rule_ref": "gate:G3"}},
        {"type": "decided_by", "from": "finding:F-1", "to": "decision:D-1",
         "meta": {"reverses": True}}]
    events = [{"kind": "park", "meta": {"slice": "slice-042",
                                         "finding_id": "F-1"}}]
    row = telemetry.summarize("slice-042", events, edges)
    assert row["reversals"] == {"gate:G3": 1, "adjudication": 1}
