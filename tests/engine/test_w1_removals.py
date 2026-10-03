"""0.10 removals (spec §7.3): G2, G4, G7, the close derived-artifacts step,
merge-slice shadow regeneration and the verify shadow-exists check."""
import json

from conftest import git, make_event, run_cli
from engine.events import handle_event
from engine.extractor.engine import shadow_path_for

GOOD_ORDERS = ("import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
               "    telemetry.emit_span('create_order', {'sku': sku})\n"
               "    return {'sku': sku}\n")


def test_builtin_pack_is_g1_g3_g5_g6_g8():
    from engine.gates import builtin_gates
    assert [g.GATE["id"] for g in builtin_gates()] == ["G1", "G3", "G5", "G6", "G8"]


def test_retired_ids_stay_reserved_for_repo_gates():
    from engine.gates import RETIRED_GATE_IDS, reserved_gate_ids
    assert RETIRED_GATE_IDS == {"G2", "G4", "G7"}
    assert {"G1", "G2", "G4", "G7", "G8"} <= reserved_gate_ids()


def test_edit_before_phase1_is_allowed(toy):
    v = handle_event(make_event("pre_change", session="no-g2",
                                files=["orders.py"]), toy)
    assert v["verdict"] == "allow", v["findings"]


def test_a_deleted_shadow_never_blocks_and_verify_passes(toy):
    shadow_path_for(toy, toy / "telemetry.py").unlink()
    v = handle_event(make_event("unit_complete", session="no-g7"), toy)
    codes = {f["code"] for f in v["findings"]}
    assert not codes & {"DERIVATION_MISMATCH", "STALE_SHADOW", "MISSING_SHADOW"}
    out = json.loads(run_cli("verify", root=toy).stdout)
    assert out["passed"], out["findings"]


def test_stale_registry_hash_is_a_g1_finding(toy):
    (toy / "telemetry.py").write_text(
        (toy / "telemetry.py").read_text() + "\ndef added(x):\n    return x\n")
    out = json.loads(run_cli("verify", root=toy).stdout)
    hits = [f for f in out["findings"] if f["code"] == "HASH_MISMATCH"]
    assert hits and hits[0]["rule_ref"] == "gate:G1"


def test_close_has_no_derived_artifacts_step(toy):
    run_cli("slice", "--slice", "slice-042", "--session", "close", root=toy)
    (toy / "orders.py").write_text(GOOD_ORDERS)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "slice-042")
    proc = run_cli("close-slice", "--slice", "slice-042", "--commit", "HEAD",
                   root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["closed"] and "shadows_extracted" not in out
