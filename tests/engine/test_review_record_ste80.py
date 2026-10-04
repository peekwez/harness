"""Spec 9.2: reviewer findings carry an STE-80 summary, a failure scenario
and a fix."""
import json

from conftest import run_cli

SUMMARY = "orders.py names a span createOrder, which breaks D-041."
SCENARIO = "A dashboard filter on snake_case span names misses every order span."


def test_record_finding_stores_fix_and_failure_scenario(toy):
    proc = run_cli("review", "--record-finding", "--slice", "slice-042",
                   "--code", "REVIEW_FINDING", "--rule-ref", "decision:D-041",
                   "--message", SUMMARY, "--fix", "Rename the span to create_order.",
                   "--failure-scenario", SCENARIO, root=toy)
    assert proc.returncode == 0, proc.stderr
    f = json.loads(proc.stdout)["finding"]
    assert f["message"] == SUMMARY
    assert f["fix"] == "Rename the span to create_order."
    assert f["inject"] == [f"Failure scenario: {SCENARIO}"]


def test_record_finding_rejects_a_summary_over_25_words(toy):
    long = " ".join(["word"] * 26)
    proc = run_cli("review", "--record-finding", "--slice", "slice-042",
                   "--rule-ref", "decision:D-041", "--message", long, root=toy)
    assert proc.returncode == 2
    assert "26 words" in proc.stderr and "25" in proc.stderr


def test_blocking_record_finding_without_fix_exits_2(toy):
    proc = run_cli("review", "--record-finding", "--slice", "slice-042",
                   "--rule-ref", "decision:D-041", "--severity", "block",
                   "--message", SUMMARY, root=toy)
    assert proc.returncode == 2
    assert "--fix" in proc.stderr and "STE-80" in proc.stderr


def test_park_keeps_the_failure_scenario_in_the_adjudication_text(toy):
    proc = run_cli("review", "--record-finding", "--park", "--slice", "slice-042",
                   "--rule-ref", "decision:D-041", "--message", SUMMARY,
                   "--failure-scenario", SCENARIO, root=toy)
    assert proc.returncode == 0, proc.stderr
    fid = json.loads(proc.stdout)["finding"]["finding_id"]
    proc = run_cli("adjudicate", "--finding-id", fid, "--resolution", "keep",
                   root=toy)
    assert proc.returncode == 0, proc.stderr
    assert "dashboard filter" in json.loads(proc.stdout)["suggest"]


def test_missing_drift_baseline_keeps_the_error_in_inject(toy, monkeypatch):
    from types import SimpleNamespace
    from engine import HarnessError
    from engine.gates import g6_drift
    import engine.baseline as baseline

    def boom(*a, **k):
        raise HarnessError("G6 baseline is missing and this slice has no "
                           "starting commit; restore it")
    monkeypatch.setattr(baseline, "ensure_baseline", boom)
    ctx = SimpleNamespace(root=toy, sidecar=None, work_unit_id="slice-042")
    (f,) = g6_drift.check(ctx)
    assert f["code"] == "MISSING_DRIFT_BASELINE"
    assert len(f["message"].split()) <= 25
    assert "no starting commit" in f["inject"][0]
    assert "starting revision" in f["fix"] and "harness slice --slice slice-042" in f["fix"]
