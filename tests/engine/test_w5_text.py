"""W5 text: the workflow names the red record and statement links (STE-80)."""
from conftest import PLUGIN_ROOT
from engine.lint_text import lint_paths

EXPECTED = {
    "skills/backlog/SKILL.md": ["--verifies", "unowned_statements",
                                "kills:"],
    "skills/build/SKILL.md": ["red_record", "green_at_start",
                              "verification:green-at-start",
                              "runner_error"],
    "skills/close-slice/SKILL.md": ["red record", "kills:",
                                    "legacy_verification"],
    "skills/verification/SKILL.md": ["verify.jsonl", "verifies:"],
    "skills/verification/design.md": ["V-<feature>-<n>: <statement>"],
    "skills/verification/checks.md": ["verification:green-at-start"],
    "agents/builder.md": ["red record", "verifies:", "kills:"],
}


def test_w5_texts_name_the_new_workflow():
    for rel, needles in EXPECTED.items():
        text = (PLUGIN_ROOT / rel).read_text()
        for needle in needles:
            assert needle in text, f"{rel} lacks {needle!r}"


def test_design_md_no_longer_says_no_engine_gate():
    text = (PLUGIN_ROOT / "skills/verification/design.md").read_text()
    assert "adds no engine schema/gate" not in text


def test_w5_texts_pass_lint_text():
    findings = lint_paths([PLUGIN_ROOT / rel for rel in EXPECTED], None)
    assert findings == [], findings
