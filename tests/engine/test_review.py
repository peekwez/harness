"""C7 acceptance: findings validate against §5.2; blocking without rule_ref
rejected by the engine itself; replay over >=10 pairs stable across three
runs; ensemble split -> park, never a majority verdict."""
import json

import pytest

from engine import load_config
from engine.events import VerdictError, validate_finding
from engine.review import assemble, replay, run_review
from engine.review.ensemble import run_ensemble

FACTS_EMPTY = {
    "slice": "slice-042", "diff_files": [], "gate_findings": [],
    "uses_declares": {"uses": [], "declares": [], "undeclared": [],
                      "unused": [], "overridden": [], "unresolved": []},
    "duplicate_candidates": [], "decisions_in_scope": [], "imported_shadows": {},
}

Q_DECISIONS = ("Does the diff conform to every decision row in scope? "
               "Answer pass/fail with the violated row id as evidence.")
Q_HOLISTIC = ("Holistic pass: anything worth a new decision row, ADR, or gate? "
              "Proposals only.")
PASS = {"answer": "pass", "confidence": 0.95, "evidence": "conforms"}


def test_findings_validate_against_schema(toy):
    config = load_config(toy)
    diff = "diff --git a/orders.py b/orders.py\n+++ b/orders.py\n+x = 1\n"
    facts = assemble(toy, diff, "slice-042", config)
    result = run_review(toy, facts, config, model=None)
    for f in result["findings"]:
        validate_finding(f)  # raises on any schema violation
        assert set(f) >= {"finding_id", "layer", "severity", "code",
                          "rule_ref", "message", "inject", "precedents"}


def test_blocking_finding_without_rule_ref_rejected_by_engine(toy):
    config = load_config(toy)
    facts = dict(FACTS_EMPTY)
    facts["gate_findings"] = [{
        "finding_id": "F-bad", "layer": 0, "severity": "block",
        "code": "UNDECLARED_USE", "rule_ref": "", "message": "no ref",
        "inject": [], "precedents": []}]
    with pytest.raises(VerdictError):
        run_review(toy, facts, config, model=None)


def test_reviewer_never_receives_builder_session_memory(toy):
    """Layer-0 facts must not contain session-memory content."""
    from engine import memory
    entry = memory.make_entry("slice-042", "reasoning",
                              "SESSION-SECRET-REASONING")
    memory.write_entry(toy, entry)
    config = load_config(toy)
    facts = assemble(toy, "", "slice-042", config)
    assert "SESSION-SECRET-REASONING" not in json.dumps(facts)


def test_replay_ten_pairs_stable_across_three_runs(toy, plugin_root):
    config = load_config(toy)
    golden = plugin_root / "tests" / "fixtures" / "golden-set"
    results = [replay(toy, golden, config) for _ in range(3)]
    for r in results:
        assert r["pairs"] >= 10
        assert r["passed"], r["failed"]
    verdict_sets = [json.dumps([x["got"] for x in r["results"]]) for r in results]
    assert len(set(verdict_sets)) == 1, "replay must be stable across runs"
    # replay is a regression check: it must not mutate the substrate
    assert not (toy / ".harness" / "parked.jsonl").exists(), \
        "replay must be side-effect-free"


def test_park_once_adjudication_prevents_repeat_park(toy):
    """M6 acceptance: an adjudication writes a decision row that prevents the
    same park on a repeat run — the same question never parks twice (§7.7)."""
    from conftest import run_cli
    from engine.review.golden import ReplayModel
    config = load_config(toy)
    outputs = {Q_DECISIONS: [
        {"answer": "fail", "confidence": 0.4, "evidence": "unsure about D-041"},
        {"answer": "pass", "confidence": 0.9, "evidence": "fine"},
        {"answer": "fail", "confidence": 0.5, "evidence": "unsure"},
    ], Q_HOLISTIC: PASS}
    first = run_review(toy, dict(FACTS_EMPTY), config, model=ReplayModel(outputs))
    assert len(first["parked"]) == 1
    fid = first["parked"][0]

    # re-running before adjudication does not duplicate the queue row
    run_review(toy, dict(FACTS_EMPTY), config, model=ReplayModel(outputs))
    queue = [l for l in (toy / ".harness" / "parked.jsonl").read_text().splitlines() if l]
    assert len(queue) == 1

    proc = run_cli("adjudicate", "--finding-id", fid,
                   "--resolution", "span naming follows D-041; conforms",
                   "--decision-id", "D-099", "--domain", "telemetry", root=toy)
    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)
    assert rows["wrote"] == "decision:D-099"

    # repeat run: the identical question does NOT park again
    third = run_review(toy, dict(FACTS_EMPTY), config, model=ReplayModel(outputs))
    assert third["parked"] == []
    precedent = [f for f in third["findings"]
                 if f["finding_id"] == fid and f["severity"] == "advisory"]
    assert precedent and "previously adjudicated" in precedent[0]["message"]
    queue = [l for l in (toy / ".harness" / "parked.jsonl").read_text().splitlines() if l]
    assert len(queue) == 0  # adjudication drained the queue


def test_adjudicate_requires_domain_with_decision_id(toy):
    from conftest import run_cli
    proc = run_cli("adjudicate", "--finding-id", "F-x", "--resolution", "r",
                   "--decision-id", "D-1", root=toy)
    assert proc.returncode == 2
    assert "--domain" in proc.stderr


def test_changed_verdict_fails_replay(toy, plugin_root, tmp_path):
    config = load_config(toy)
    golden = plugin_root / "tests" / "fixtures" / "golden-set"
    corrupt = tmp_path / "golden"
    corrupt.mkdir()
    for p in golden.glob("*.json"):
        (corrupt / p.name).write_text(p.read_text())
    victim = json.loads((corrupt / "pair-01.json").read_text())
    victim["verdict"] = "block"  # adjudicated verdict was allow
    (corrupt / "pair-01.json").write_text(json.dumps(victim))
    result = replay(toy, corrupt, config)
    assert not result["passed"]
    assert any(f["pair"] == "pair-01.json" for f in result["failed"])


def test_ensemble_split_escalates_uncertain_never_average():
    outs = iter([
        {"answer": "fail", "confidence": 0.9, "evidence": "a"},
        {"answer": "pass", "confidence": 0.9, "evidence": "b"},
        {"answer": "fail", "confidence": 0.9, "evidence": "c"},
    ])
    result = run_ensemble(lambda q, c: next(outs), "q", {}, 3)
    assert result["answer"] == "uncertain"
    assert "split" in result["evidence"]


def test_ensemble_split_parks_with_gate_severity(toy):
    """A split on a would-block rubric produces severity gate -> park."""
    config = load_config(toy)
    outputs = {Q_DECISIONS: [
        {"answer": "fail", "confidence": 0.4, "evidence": "low-confidence fail"},
        {"answer": "pass", "confidence": 0.9, "evidence": "looks fine"},
        {"answer": "fail", "confidence": 0.6, "evidence": "maybe D-041"},
    ], Q_HOLISTIC: PASS}
    from engine.review.golden import ReplayModel
    result = run_review(toy, dict(FACTS_EMPTY), config,
                        model=ReplayModel(outputs))
    parked = [f for f in result["findings"] if f["code"] == "REVIEW_UNCERTAIN"]
    assert parked and parked[0]["severity"] == "gate"
    assert result["verdict"] == "allow_with_findings"  # parked, not blocked
    assert result["parked"] == [parked[0]["finding_id"]]
    queue = (toy / ".harness" / "parked.jsonl").read_text()
    assert parked[0]["finding_id"] in queue


def test_layer3_is_advisory_only(toy):
    config = load_config(toy)
    from engine.review.golden import ReplayModel
    result = run_review(toy, dict(FACTS_EMPTY), config, model=ReplayModel({
        Q_DECISIONS: PASS,
        Q_HOLISTIC: {"answer": "fail", "confidence": 0.99,
                     "evidence": "propose D-100: span budget rule"}}))
    l3 = [f for f in result["findings"] if f["layer"] == 3]
    assert l3 and all(f["severity"] == "advisory" for f in l3)
    assert result["verdict"] != "block"
