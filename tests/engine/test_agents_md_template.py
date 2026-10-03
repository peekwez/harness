"""AGENTS.md template (spec §7.6): short, rules and pointers only."""
from conftest import PLUGIN_ROOT

TEMPLATE = PLUGIN_ROOT / "templates" / "agents-md.md"


def test_template_is_45_lines_or_fewer():
    assert len(TEMPLATE.read_text().splitlines()) <= 45


def test_template_keeps_binding_rules_stop_conditions_and_workflow():
    body = TEMPLATE.read_text()
    for needle in ("<!-- harness:agents-md 0.10 -->", "## Binding rules",
                   "## Autonomy: when to stop", "## Workflow",
                   "harness resolve --module", "parked review finding",
                   "author-gate", "close-slice", "rule_ref"):
        assert needle in body, needle


def test_template_points_to_skills_instead_of_long_sections():
    body = TEMPLATE.read_text()
    assert "D-014" in body and "harness:build" in body
    assert "harness:review" in body and "harness:verification" in body
    for gone in ("## Precedence when superpowers is installed",
                 "## Gates you will meet", "## Independent code review",
                 ".harness/shadows", "memory write"):
        assert gone not in body, gone
