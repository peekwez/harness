"""Spec 9.2: review layer 0 flags glossary synonyms in a diff (advisory)."""
from engine import load_config
from engine.review.layer0 import _glossary_findings, assemble

GLOSSARY = "- **slice** — the smallest unit of work (not: story, ticket)\n"


def _diff(path, *added):
    body = "".join(f"+{line}\n" for line in added)
    return (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
            f"@@ -0,0 +1,{len(added)} @@\n{body}")


def _write(toy, path, text):
    f = toy / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)


def _glossary(toy):
    (toy / "docs").mkdir(exist_ok=True)
    (toy / "docs" / "glossary.md").write_text(GLOSSARY)


def test_layer0_flags_glossary_synonyms_in_markdown(toy):
    _glossary(toy)
    _write(toy, "docs/guide.md", "Each story gets one branch.\nPlain line.\n")
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
    _write(toy, "docs/a.md", "A story.\n\nA story.\n")
    hits = _glossary_findings(toy, _diff("docs/a.md", "A story.", "", "A story."))
    assert len(hits) == 1


def test_layer0_ignores_code_files_and_inline_code(toy):
    _glossary(toy)
    _write(toy, "orders.py", "story = 1\n")
    assert _glossary_findings(toy, _diff("orders.py", "story = 1")) == []
    for text in ("Run `story`.", "The history.", "See user_story_id here."):
        _write(toy, "docs/a.md", text + "\n")
        assert _glossary_findings(toy, _diff("docs/a.md", text)) == [], text


def test_layer0_skips_the_glossary_itself_and_a_missing_glossary(toy):
    _write(toy, "docs/a.md", "A story.\n")
    assert _glossary_findings(toy, _diff("docs/a.md", "A story.")) == []
    _glossary(toy)
    assert _glossary_findings(
        toy, _diff("docs/glossary.md", "- **x** — y (not: story)")) == []


def test_assemble_adds_glossary_findings_to_gate_findings(toy):
    _glossary(toy)
    _write(toy, "docs/guide.md", "One story.\n")
    facts = assemble(toy, _diff("docs/guide.md", "One story."), "slice-042",
                     load_config(toy))
    assert any(f["code"] == "GLOSSARY_SYNONYM" for f in facts["gate_findings"])


def test_layer0_skips_what_lint_text_skips(toy):
    _glossary(toy)
    cases = {
        "fence": "```\nstory\n```\n",
        "heading": "# Story\n",
        "table": "| story |\n| --- |\n",
        "comment": "<!-- story -->\n",
        "front matter": "---\ntitle: story\n---\nPlain.\n",
    }
    for name, text in cases.items():
        _write(toy, "docs/a.md", text)
        added = text.splitlines()
        assert _glossary_findings(toy, _diff("docs/a.md", *added)) == [], name


def test_layer0_flags_only_added_lines_and_any_suffix_case(toy):
    _glossary(toy)
    _write(toy, "docs/A.MD", "Old story line.\nNew story line.\n")
    diff = ("diff --git a/docs/A.MD b/docs/A.MD\n--- a/docs/A.MD\n"
            "+++ b/docs/A.MD\n@@ -1,1 +1,2 @@\n Old story line.\n"
            "+New story line.\n")
    assert len(_glossary_findings(toy, diff)) == 1
    unchanged = diff.replace("+New", " New")
    assert _glossary_findings(toy, unchanged.replace("1,2", "1,2")) == []


def test_layer0_survives_a_deleted_file_and_plus_lookalikes(toy):
    _glossary(toy)
    gone = ("diff --git a/docs/x.md b/docs/x.md\n--- a/docs/x.md\n"
            "+++ /dev/null\n@@ -1,1 +0,0 @@\n-A story.\n")
    assert _glossary_findings(toy, gone) == []
    _write(toy, "docs/a.md", "++ b/other.md story\n")
    assert _glossary_findings(toy, _diff("docs/a.md", "++ b/other.md story")) \
        [0]["message"].startswith("docs/a.md:")
