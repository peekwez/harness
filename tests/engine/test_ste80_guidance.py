"""Spec 7.6 and 9.2: AGENTS.md carries one STE-80 rule; ste80.md holds the
rules; the reviewer writes summary and failure_scenario in STE-80."""
from conftest import PLUGIN_ROOT
from engine import upgrade_010
from engine.lint_text import lint_paths
from engine.upgrade_w4 import AGENTS_STE80_STEP, STE80_RULE

TEMPLATE = PLUGIN_ROOT / "templates" / "agents-md.md"
GUIDE = PLUGIN_ROOT / "skills" / "harness" / "ste80.md"
REVIEWER = PLUGIN_ROOT / "agents" / "reviewer.md"
MARKER = "<!-- harness:agents-md 0.10 -->"


def test_agents_md_template_has_one_numbered_ste80_rule_and_fits():
    lines = TEMPLATE.read_text().splitlines()
    assert len(lines) <= 45
    ste = [line for line in lines if "STE-80" in line]
    assert len(ste) == 1
    assert ste[0].startswith("6. ") and "ste80.md" in ste[0]
    assert ste[0] == STE80_RULE


def test_agents_md_template_passes_lint_text():
    assert lint_paths([TEMPLATE], None) == []


def test_ste80_guide_passes_lint_text_and_names_the_replacements():
    assert lint_paths([GUIDE], None) == []
    text = GUIDE.read_text()
    for word in ("utilize", "leverage", "in order to", "prior to", "simply",
                 "robust", "150 words", "failure_scenario", "fix"):
        assert word in text, word


def test_harness_skill_points_at_the_guide():
    assert "ste80.md" in (PLUGIN_ROOT / "skills" / "harness" / "SKILL.md").read_text()


def test_reviewer_writes_summary_and_failure_scenario_in_ste80():
    text = REVIEWER.read_text()
    for needle in ("summary", "failure_scenario", "--failure-scenario",
                   "--fix", "25 words", "ste80.md"):
        assert needle in text, needle


def test_review_docs_name_the_new_flags():
    for rel in ("skills/review/SKILL.md", "skills/review/rubrics.md"):
        text = (PLUGIN_ROOT / rel).read_text()
        for needle in ("--fix", "--failure-scenario", "25 words"):
            assert needle in text, (rel, needle)


# ------------------------------------------------- w4.agents-md-ste80 step
def _old(toy, marker=MARKER):
    body = TEMPLATE.read_text().replace(STE80_RULE + "\n", "")
    body = body.replace(MARKER, marker)
    (toy / "AGENTS.md").write_text(body)
    return body


def test_step_is_registered_after_glossary():
    ids = [s.id for s in upgrade_010.STEPS if s.id.startswith("w4.")]
    assert ids == ["w4.glossary", "w4.agents-md-ste80"]


def test_step_inserts_the_rule_as_the_next_number_once(tmp_path):
    _old(tmp_path)
    assert AGENTS_STE80_STEP.describe(tmp_path)
    AGENTS_STE80_STEP.apply(tmp_path, lambda q: True)
    text = (tmp_path / "AGENTS.md").read_text()
    assert text == TEMPLATE.read_text()
    assert AGENTS_STE80_STEP.describe(tmp_path) == []
    AGENTS_STE80_STEP.apply(tmp_path, lambda q: True)
    assert (tmp_path / "AGENTS.md").read_text() == text


def test_step_advises_and_never_edits_an_unmarked_file(tmp_path):
    body = _old(tmp_path, marker="<!-- other -->")
    assert AGENTS_STE80_STEP.describe(tmp_path) == []
    assert AGENTS_STE80_STEP.apply(tmp_path, lambda q: True) == []
    advice = AGENTS_STE80_STEP.advise(tmp_path)
    assert advice and advice[0].startswith("check:")
    assert (tmp_path / "AGENTS.md").read_text() == body


def test_step_is_silent_without_agents_md_or_when_rule_present(tmp_path):
    assert AGENTS_STE80_STEP.describe(tmp_path) == []
    assert AGENTS_STE80_STEP.advise(tmp_path) == []
    (tmp_path / "AGENTS.md").write_text(TEMPLATE.read_text())
    assert AGENTS_STE80_STEP.describe(tmp_path) == []
    assert AGENTS_STE80_STEP.advise(tmp_path) == []
