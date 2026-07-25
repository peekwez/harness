"""C6 acceptance: positive + negative fixture per gate; G2 pointer <=400
tokens with shadow path; G5 override edge auditable; G7 catches hand-edits."""
import json

import pytest

from conftest import loaded_context, make_event
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


# ---------------------------------------------------------------- G2
def test_g2_blocks_without_context_with_pointer(toy):
    v = handle_event(make_event("pre_change", session="g2n",
                                files=["orders.py"]), toy)
    assert v["verdict"] == "block"
    g2 = [f for f in v["findings"]
          if f["code"] in ("CONTEXT_NOT_LOADED", "MISSING_SHADOW")]
    assert g2
    for f in g2:
        assert f["rule_ref"] == "gate:G2"
        pointer = "\n".join(f["inject"])
        assert token_estimate(pointer) <= 400, "pointer must be pointer-sized"
    shadow_pointers = [f for f in g2 if "shadow" in "\n".join(f["inject"])]
    assert any(".harness/shadows/telemetry.py.json" in "\n".join(f["inject"])
               for f in shadow_pointers), "deny reason must contain the shadow path"


def test_g2_allows_after_phase1_injection(toy):
    loaded_context(toy, session="g2p")
    v = handle_event(make_event("pre_change", session="g2p",
                                files=["orders.py"]), toy)
    assert v["verdict"] == "allow", v["findings"]


# ---------------------------------------------------------------- G3
def test_g3_default_allow_with_findings(toy):
    loaded_context(toy, session="g3d")
    v = handle_event(make_event("pre_change", session="g3d",
                                files=["rogue.py"]), toy)
    assert v["verdict"] == "allow_with_findings"
    assert "UNDECLARED_FILE" in codes(v)


def test_g3_block_mode(tmp_path):
    from conftest import build_toy_repo
    toy = build_toy_repo(tmp_path / "toy", g3_mode="block")
    loaded_context(toy, session="g3b")
    v = handle_event(make_event("pre_change", session="g3b",
                                files=["rogue.py"]), toy)
    assert v["verdict"] == "block"


def test_g3_radius_mode_same_package_allowed(tmp_path):
    from conftest import build_toy_repo
    toy = build_toy_repo(tmp_path / "toy", g3_mode="radius")
    loaded_context(toy, session="g3r")
    v = handle_event(make_event("pre_change", session="g3r",
                                files=["neighbor.py"]), toy)  # same dir as orders.py
    assert "UNDECLARED_FILE" not in codes(v)


def test_g3_non_goal_boundary_always_blocks(toy):
    loaded_context(toy, session="g3ng")
    v = handle_event(make_event("pre_change", session="g3ng",
                                files=["legacy/exporter.py"]), toy)
    assert v["verdict"] == "block"
    hits = [f for f in v["findings"] if f["code"] == "NON_GOAL_VIOLATION"]
    assert hits and hits[0]["rule_ref"] == "adr:007"


# ---------------------------------------------------------------- G4
def test_g4_blocks_on_stale_shadow_with_refresh_pointer(toy):
    loaded_context(toy, session="g4n")
    (toy / "telemetry.py").write_text(
        open(toy / "telemetry.py").read() + "\n\ndef extra(x):\n    return x\n")
    v = handle_event(make_event("pre_change", session="g4n",
                                files=["orders.py"]), toy)
    assert v["verdict"] == "block"
    stale = [f for f in v["findings"] if f["code"] == "STALE_SHADOW"]
    assert stale and "harness extract" in "\n".join(stale[0]["inject"])


def test_g4_fresh_passes(toy):
    loaded_context(toy, session="g4p")
    v = handle_event(make_event("pre_change", session="g4p",
                                files=["orders.py"]), toy)
    assert "STALE_SHADOW" not in codes(v)


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


def test_g5_undeclared_use_blocks_and_override_is_auditable(toy):
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
    assert v["verdict"] == "block"
    hits = [f for f in v["findings"] if f["code"] == "UNDECLARED_USE"]
    assert hits and hits[0]["rule_ref"] == "gate:G5"

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


# ---------------------------------------------------------------- G7
def test_g7_catches_hand_edited_shadow(toy):
    session = "g7"
    loaded_context(toy, session=session)
    sp = toy / ".harness" / "shadows" / "telemetry.py.json"
    shadow = json.loads(sp.read_text())
    shadow["symbols"][0]["signature"] = "def emit_span(hacked)"
    sp.write_text(json.dumps(shadow, sort_keys=True, indent=1) + "\n")
    v = handle_event(make_event("unit_complete", session=session), toy)
    assert v["verdict"] == "block"
    assert "DERIVATION_MISMATCH" in codes(v)


# ---------------------------------------------------------------- G8
def test_g8_coverage_advisory_always_emitted(toy):
    session = "g8"
    loaded_context(toy, session=session)
    (toy / "main.go").write_text("package main\n")
    v = handle_event(make_event("post_change", session=session,
                                files=["main.go"]), toy)
    assert "UNSHADOWED_FILE" in codes(v)
    assert v["verdict"] == "allow_with_findings"  # advisory, never a block
