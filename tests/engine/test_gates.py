"""C6 acceptance: positive + negative fixture per gate; G5 override edge
auditable. G2, G4 and G7 were removed in 0.10."""
import json

import pytest

from conftest import cite_non_goals, loaded_context, make_event
from engine import load_config, token_estimate
from engine.events import handle_event


def codes(v):
    return {f["code"] for f in v["findings"]}


# ---------------------------------------------------------------- G1
def test_g1_positive(toy):
    v = handle_event(make_event("session_start", session="g1p"), toy)
    assert "MANIFEST_INCOMPLETE" not in codes(v)


def test_g1_negative_missing_acceptance(toy):
    (toy / "tests" / "slices" / "042_orders.py").unlink()
    v = handle_event(make_event("session_start", session="g1n"), toy)
    assert v["verdict"] == "block"
    assert "MANIFEST_INCOMPLETE" in codes(v)


# ---------------------------------------------------------------- G3
def test_g3_default_allow_with_findings(toy):
    loaded_context(toy, session="g3d")
    v = handle_event(make_event("pre_change", session="g3d",
                                files=["rogue.py"]), toy)
    assert v["verdict"] == "allow_with_findings"
    assert "UNDECLARED_FILE" in codes(v)


def test_g3_radius_mode_same_package_allowed(tmp_path):
    from conftest import build_toy_repo
    toy = build_toy_repo(tmp_path / "toy", g3_mode="radius")
    loaded_context(toy, session="g3r")
    v = handle_event(make_event("pre_change", session="g3r",
                                files=["neighbor.py"]), toy)  # same dir as orders.py
    assert "UNDECLARED_FILE" not in codes(v)


def test_g3_cited_non_goal_blocks(toy):
    cite_non_goals(toy, "adr:007")
    loaded_context(toy, session="g3ng")
    v = handle_event(make_event("pre_change", session="g3ng",
                                files=["legacy/exporter.py"]), toy)
    assert v["verdict"] == "block"
    hits = [f for f in v["findings"] if f["code"] == "NON_GOAL_VIOLATION"]
    assert hits and hits[0]["rule_ref"] == "adr:007"


# ---------------------------------------------------------------- G5
def _write_orders_using_config(toy, session):
    """orders.py imports config, which slice-042 DOES declare — fine;
    then rogue.py imports telemetry without declaring."""
    loaded_context(toy, session=session)
    (toy / "orders.py").write_text(
        "import telemetry\n\ndef create_order(sku):\n"
        "    telemetry.emit_span('create_order', {})\n    return {'sku': sku}\n")
    handle_event(make_event("post_change", session=session,
                            files=["orders.py"]), toy)


def test_g5_undeclared_use_advises_and_override_is_auditable(toy):
    session = "g5n"
    loaded_context(toy, session=session)
    from engine import read_jsonl, write_jsonl
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["declares_dep"] = ["config"]  # undeclare telemetry
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    (toy / "orders.py").write_text(
        "import telemetry\n\ndef create_order(sku):\n"
        "    return telemetry.emit_span('create_order', {})\n")
    handle_event(make_event("post_change", session=session,
                            files=["orders.py"]), toy)
    # unit_complete regenerates the shadow, then G5 sees the undeclared use
    v = handle_event(make_event("unit_complete", session=session), toy)
    assert v["verdict"] != "block"
    hits = [f for f in v["findings"] if f["code"] == "UNDECLARED_USE"]
    assert hits and hits[0]["rule_ref"] == "gate:G5"
    assert hits[0]["severity"] == "advisory"

    # builder override with recorded justification -> auditable edge
    from engine.gates.g5_conformance import record_override
    edge = record_override(toy, "slice-042", "module:telemetry",
                           "read-only span emission, no coupling", hits[0]["finding_id"])
    assert edge["type"] == "override"
    assert edge["meta"]["justification"]
    from engine.graph import load_edges
    stored = [e for e in load_edges(toy) if e["type"] == "override"]
    assert stored and stored[0]["meta"]["justification"].startswith("read-only")

    v2 = handle_event(make_event("unit_complete", session=session), toy)
    assert "UNDECLARED_USE" not in codes(v2)


def test_g5_override_requires_justification(toy):
    from engine import HarnessError
    from engine.gates.g5_conformance import record_override
    with pytest.raises(HarnessError):
        record_override(toy, "slice-042", "module:telemetry", "   ")


def test_g5_duplicate_candidate_vs_signature_digest(toy):
    session = "g5dup"
    loaded_context(toy, session=session)
    # a new module re-implementing telemetry's public surface
    (toy / "orders.py").write_text(
        '"""Orders."""\n\ndef emit_span(name: str, attrs: dict) -> dict:\n'
        '    return {"name": name, "attrs": attrs}\n')
    handle_event(make_event("post_change", session=session,
                            files=["orders.py"]), toy)
    v = handle_event(make_event("unit_complete", session=session), toy)
    dups = [f for f in v["findings"] if f["code"] == "DUPLICATE_CANDIDATE"]
    assert dups, v["findings"]
    assert "telemetry" in dups[0]["message"]


# ---------------------------------------------------------------- G6
def test_g6_drift_blocks_until_acknowledged(toy):
    session = "g6"
    loaded_context(toy, session=session)  # snapshot baseline
    (toy / "telemetry.py").write_text(
        TELEMETRY_CHANGED := open(toy / "telemetry.py").read().replace(
            "def emit_span(name: str, attrs: dict) -> dict:",
            "def emit_span(name: str, attrs: dict, level: int = 0) -> dict:"))
    # touch it so unit_complete regenerates the shadow
    handle_event(make_event("post_change", session=session,
                            files=["telemetry.py"]), toy)
    v = handle_event(make_event("unit_complete", session=session), toy)
    drift = [f for f in v["findings"] if f["code"] == "INTERFACE_DRIFT"]
    assert drift and v["verdict"] == "block"
    assert "ack-drift" in drift[0]["message"]

    from engine.gates.g6_drift import acknowledge
    edge = acknowledge(toy, "slice-042", "telemetry", "level param approved in review")
    assert edge["meta"]["rule_ref"] == "gate:G6"
    v2 = handle_event(make_event("unit_complete", session=session), toy)
    assert "INTERFACE_DRIFT" not in codes(v2)


# ---------------------------------------------------------------- G8
def test_g8_coverage_advisory_always_emitted(toy):
    session = "g8"
    loaded_context(toy, session=session)
    (toy / "main.rb").write_text("puts 1\n")
    v = handle_event(make_event("post_change", session=session,
                                files=["main.rb"]), toy)
    assert "UNSHADOWED_FILE" in codes(v)
    assert v["verdict"] == "allow_with_findings"  # advisory, never a block
