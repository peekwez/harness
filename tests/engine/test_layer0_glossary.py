"""Spec 9.2: review layer 0 flags glossary synonyms in a diff (advisory)."""
from engine import load_config
from engine.review.layer0 import _glossary_findings, assemble

GLOSSARY = "- **slice** — the smallest unit of work (not: story, ticket)\n"


def _diff(path, *added):
    body = "".join(f"+{line}\n" for line in added)
    return (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
            f"@@ -0,0 +1,{len(added)} @@\n{body}")


def _glossary(toy):
    (toy / "docs").mkdir(exist_ok=True)
    (toy / "docs" / "glossary.md").write_text(GLOSSARY)


def test_layer0_flags_glossary_synonyms_in_markdown(toy):
    _glossary(toy)
    hits = _glossary_findings(toy, _diff("docs/guide.md",
                                         "Each story gets one branch.",
                                         "Plain line."))
    assert [h["code"] for h in hits] == ["GLOSSARY_SYNONYM"]
    h = hits[0]
    assert h["severity"] == "advisory" and h["rule_ref"] == "review:layer0"
    assert h["message"] == ("docs/guide.md: added text uses 'story'; the "
                            "glossary term is 'slice'.")
    assert "'slice'" in h["fix"]


def test_layer0_reports_each_synonym_once_per_file(toy):
    _glossary(toy)
    hits = _glossary_findings(toy, _diff("docs/a.md", "A story.", "A story."))
    assert len(hits) == 1


def test_layer0_ignores_code_files_and_inline_code(toy):
    _glossary(toy)
    assert _glossary_findings(toy, _diff("orders.py", "story = 1")) == []
    assert _glossary_findings(toy, _diff("docs/a.md", "Run `story`.")) == []
    assert _glossary_findings(toy, _diff("docs/a.md", "The history.")) == []


def test_layer0_skips_the_glossary_itself_and_a_missing_glossary(toy):
    assert _glossary_findings(toy, _diff("docs/a.md", "A story.")) == []
    _glossary(toy)
    assert _glossary_findings(
        toy, _diff("docs/glossary.md", "- **x** — y (not: story)")) == []


def test_assemble_adds_glossary_findings_to_gate_findings(toy):
    _glossary(toy)
    facts = assemble(toy, _diff("docs/guide.md", "One story."), "slice-042",
                     load_config(toy))
    assert any(f["code"] == "GLOSSARY_SYNONYM" for f in facts["gate_findings"])
