"""Spec 4.1: a non-goal blocks only when a gates.extra gate cites it in
GATE["cites"] (boundary id or rule ref). compile reports the others as
advisory only."""
import yaml

from conftest import cite_non_goals, finding_text, make_event
from engine import load_config, read_jsonl
from engine.compiler import compile_substrate
from engine.events import handle_event
from engine.gates.extra import cited_rules, load_extra_gates


def _non_goal(verdict):
    return [f for f in verdict["findings"] if f["code"] == "NON_GOAL_VIOLATION"]


def _edit_legacy(toy, session):
    return handle_event(make_event("pre_change", session=session,
                                   files=["legacy/exporter.py"]), toy)


def test_uncited_non_goal_is_advisory(toy):
    v = _edit_legacy(toy, "ng-uncited")
    hits = _non_goal(v)
    assert hits and all(f["severity"] == "advisory" for f in hits)
    assert v["verdict"] == "allow_with_findings"
    assert "B-legacy" in finding_text(hits[0])
    assert finding_text(hits[0]).endswith(
        'Cite adr:007 in a gates.extra GATE["cites"].')


def test_non_goal_cited_by_boundary_id_blocks(toy):
    cite_non_goals(toy, "B-legacy")
    v = _edit_legacy(toy, "ng-id")
    hits = _non_goal(v)
    assert v["verdict"] == "block"
    assert hits[0]["severity"] == "block" and hits[0]["rule_ref"] == "adr:007"
    assert "boundary:B-legacy" in finding_text(hits[0])


def test_non_goal_cited_by_rule_ref_blocks(toy):
    cite_non_goals(toy, "adr:007")
    assert _edit_legacy(toy, "ng-ref")["verdict"] == "block"


def test_cited_rules_unions_every_gate(toy):
    cite_non_goals(toy, "B-legacy", "adr:007")
    gates, errors = load_extra_gates(toy, load_config(toy))
    assert errors == []
    assert cited_rules(gates) == {"B-legacy", "adr:007"}


def test_cites_must_be_a_list_of_strings(toy):
    gdir = toy / ".harness" / "gates"
    gdir.mkdir(parents=True, exist_ok=True)
    (gdir / "bad_cites.py").write_text(
        'GATE = {"id": "BAD", "preferred": ["unit_complete"], '
        '"cites": "B-legacy"}\n\ndef run(ctx):\n    return []\n')
    cfg_path = toy / ".harness" / "config.yaml"
    doc = yaml.safe_load(cfg_path.read_text())
    doc["gates"]["extra"] = [".harness/gates/bad_cites.py"]
    cfg_path.write_text(yaml.safe_dump(doc, sort_keys=False))
    gates, errors = load_extra_gates(toy, load_config(toy))
    assert gates == []
    assert errors[0]["code"] == "EXTRA_GATE_LOAD_ERROR"
    assert "cites" in errors[0]["message"]


def test_broken_citing_gate_still_blocks(toy):
    """Review Focus 5: a citing gate that fails to load never turns a cited
    non-goal into a quiet advisory."""
    cite_non_goals(toy, "adr:007")
    (toy / ".harness" / "gates" / "toy_cites.py").write_text(
        "raise ImportError('deliberate')\n")
    v = _edit_legacy(toy, "ng-broken")
    assert v["verdict"] == "block"
    assert any(f["code"] == "EXTRA_GATE_LOAD_ERROR" for f in v["findings"])


def test_compile_reports_uncited_non_goals_as_advisory_only(toy):
    report = compile_substrate(toy)
    legacy = [b["id"] for b in read_jsonl(toy / ".harness" / "boundaries.jsonl")
              if "legacy/**" in b["patterns"]]
    assert legacy and set(legacy) <= set(report["advisory_only"])
    assert any("advisory only" in w for w in report["warnings"])


def test_compile_does_not_flag_cited_non_goals(toy):
    cite_non_goals(toy, "adr:007")
    report = compile_substrate(toy)
    assert report["advisory_only"] == []


def test_compile_advisory_warning_names_the_rule_ref(toy):
    report = compile_substrate(toy)
    advisory = [w for w in report["warnings"] if "advisory only" in w]
    assert advisory and all("Cite adr:007" in w for w in advisory)


def test_compile_warns_on_a_stale_cite(toy):
    """I1: an edited non-goal gets a new hash id; the old cite must not go
    quiet."""
    cite_non_goals(toy, "B-deadbeef", "adr:007")
    report = compile_substrate(toy)
    assert ("cites entry B-deadbeef matches no non-goal. Fix the cite or "
            "the non-goal.") in report["warnings"]
    assert not any("cites entry adr:007" in w for w in report["warnings"])


def test_compile_reports_extra_gate_load_errors(toy):
    """R4: a broken citing gate is named, not just its non-goals listed as
    advisory only."""
    cite_non_goals(toy, "adr:007")
    (toy / ".harness" / "gates" / "toy_cites.py").write_text(
        "raise ImportError('deliberate')\n")
    report = compile_substrate(toy)
    assert any("toy_cites.py" in w and "failed to load" in w
               and "deliberate" in w for w in report["warnings"])


def test_template_example_cites_a_rule_ref_not_a_hash_id():
    from conftest import PLUGIN_ROOT
    text = (PLUGIN_ROOT / "templates" / "harness.yaml").read_text()
    assert "B-1a2b3c4d" not in text
    assert '"cites": ["adr:007"]' in text
