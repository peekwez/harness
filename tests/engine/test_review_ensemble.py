"""Spec 10.3: ensemble sampling and golden replay are opt-in
(`review.ensemble: true`). Default off."""
import json

import yaml

from conftest import run_cli
from engine import DEFAULT_CONFIG, load_config
from engine.review import run_review
from engine.review.golden import ReplayModel
from test_review import FACTS_EMPTY, PASS, Q_DECISIONS, Q_HOLISTIC

LOW_CONFIDENCE_SPLIT = {Q_DECISIONS: [
    {"answer": "fail", "confidence": 0.4, "evidence": "low-confidence fail"},
    {"answer": "pass", "confidence": 0.9, "evidence": "looks fine"},
    {"answer": "fail", "confidence": 0.6, "evidence": "maybe D-041"},
], Q_HOLISTIC: PASS}


class CountingModel:
    def __init__(self, outputs):
        self.inner = ReplayModel(outputs)
        self.calls = {}

    def __call__(self, question, context):
        self.calls[question] = self.calls.get(question, 0) + 1
        return self.inner(question, context)


def _config(toy, on):
    config = load_config(toy)
    config["review"]["ensemble"] = on
    return config


def _opt_in(toy):
    cfg_path = toy / ".harness" / "config.yaml"
    doc = yaml.safe_load(cfg_path.read_text())
    doc.setdefault("review", {})["ensemble"] = True
    cfg_path.write_text(yaml.safe_dump(doc, sort_keys=False))


def test_ensemble_is_off_by_default(toy):
    assert "ensemble" not in DEFAULT_CONFIG
    assert DEFAULT_CONFIG["review"]["ensemble"] is False
    assert load_config(toy)["review"]["ensemble"] is False


def test_off_parks_a_low_confidence_block_without_resampling(toy):
    model = CountingModel(LOW_CONFIDENCE_SPLIT)
    result = run_review(toy, dict(FACTS_EMPTY), _config(toy, False), model=model)
    assert model.calls[Q_DECISIONS] == 1
    parked = [f for f in result["findings"] if f["code"] == "REVIEW_UNCERTAIN"]
    assert parked and parked[0]["severity"] == "gate"
    assert result["verdict"] == "allow_with_findings"
    assert "review.ensemble is off" in parked[0]["message"]


def test_on_resamples_three_times(toy):
    model = CountingModel(LOW_CONFIDENCE_SPLIT)
    run_review(toy, dict(FACTS_EMPTY), _config(toy, True), model=model)
    assert model.calls[Q_DECISIONS] == 1 + 3


def test_replay_cli_refuses_when_off(toy):
    proc = run_cli("review", "--replay", root=toy)
    assert proc.returncode == 2
    assert "review.ensemble" in proc.stderr


def test_replay_cli_runs_when_on(toy):
    _opt_in(toy)
    proc = run_cli("review", "--replay", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["passed"] is True
