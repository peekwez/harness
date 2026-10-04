"""STE-80 text lint (spec 9.3): sentence length, banned words, glossary
synonyms; code blocks and front matter are skipped."""
import pytest

from engine.lint_text import (BANNED, find_synonyms, format_row, lint_paths,
                              lint_text, load_glossary, scaffold_glossary)


def words(n: int) -> str:
    return " ".join(["word"] * n)


def rules(rows):
    return [r["rule"] for r in rows]


def test_list_item_over_25_words_is_flagged_and_25_is_not():
    assert lint_text(f"- {words(25)}.\n", "a.md") == []
    rows = lint_text(f"- {words(26)}.\n", "a.md")
    assert rules(rows) == ["sentence-length"]
    assert rows[0]["line"] == 1 and "26 words, limit 25" in rows[0]["text"]


def test_numbered_step_uses_the_list_limit():
    assert rules(lint_text(f"1. {words(26)}.\n", "a.md")) == ["sentence-length"]


def test_prose_over_35_words_is_flagged_and_35_is_not():
    assert lint_text(f"{words(35)}.\n", "a.md") == []
    assert rules(lint_text(f"{words(36)}.\n", "a.md")) == ["sentence-length"]


def test_wrapped_prose_is_one_sentence_reported_at_its_first_line():
    text = "Intro.\n\n" + f"{words(20)}\n{words(20)}.\n"
    rows = lint_text(text, "a.md")
    assert [(r["rule"], r["line"]) for r in rows] == [("sentence-length", 3)]


def test_each_sentence_is_measured_on_its_own():
    assert lint_text(f"- {words(20)}. {words(20)}.\n", "a.md") == []


def test_banned_words_match_whole_words_and_phrases_case_insensitively():
    rows = lint_text("We Utilize it in order to ship.\n", "a.md")
    assert sorted(r["text"] for r in rows) == [
        "'in order to': write a plain word", "'utilize': write a plain word"]
    assert lint_text("Simplyfy nothing.\n", "a.md") == []


def test_banned_list_covers_the_spec_examples():
    for word in ("utilize", "leverage", "simply", "robust", "in order to"):
        assert word in BANNED


def test_fenced_code_front_matter_tables_and_comments_are_skipped():
    text = ("---\ntitle: simply robust\n---\n"
            "```\nutilize leverage simply\n```\n"
            "| simply | robust |\n"
            "<!-- leverage -->\n"
            "Plain text.\n")
    assert lint_text(text, "a.md") == []


def test_inline_code_counts_as_one_word_and_is_not_checked():
    assert lint_text("Run `harness lint-text --simply robust`.\n", "a.md") == []


def test_unclosed_fence_is_a_finding_not_a_silent_skip():
    rows = lint_text("Text.\n```\ncode\n", "a.md")
    assert [(r["rule"], r["line"]) for r in rows] == [("unclosed-fence", 2)]


def test_glossary_synonyms_name_the_term(tmp_path):
    g = tmp_path / "glossary.md"
    g.write_text("# Glossary\n\n"
                 "- **slice** — the smallest unit of work (not: story, work item)\n"
                 "- **gate** — a deterministic check\n")
    assert load_glossary(g) == {"story": "slice", "work item": "slice"}
    rows = lint_text("Each Story has one branch.\n", "a.md", load_glossary(g))
    assert [(r["rule"], r["text"]) for r in rows] == [
        ("glossary-synonym", "'story': use 'slice'")]
    assert lint_text("Read the history.\n", "a.md", load_glossary(g)) == []
    assert lint_text("Run `story`.\n", "a.md", load_glossary(g)) == []


def test_find_synonyms_skips_inline_code():
    g = {"story": "slice"}
    assert find_synonyms("One story here.", g) == [("story", "slice")]
    assert find_synonyms("Run `story` now.", g) == []


def test_missing_glossary_adds_no_synonyms(tmp_path):
    assert load_glossary(tmp_path / "nope.md") == {}
    assert load_glossary(None) == {}


def test_lint_paths_walks_markdown_and_skips_the_glossary_itself(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    g = docs / "glossary.md"
    g.write_text("- **slice** — the unit of work (not: story)\n")
    (docs / "guide.md").write_text("A story.\n")
    (docs / "notes.txt").write_text("utilize\n")
    rows = lint_paths([docs], g)
    assert [format_row(r) for r in rows] == [
        f"{docs / 'guide.md'}:1: glossary-synonym: 'story': use 'slice'"]


def test_lint_paths_reports_non_utf8_files(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"\xff\xfe\xfa text\n")
    assert rules(lint_paths([bad], None)) == ["encoding"]


def test_lint_paths_accepts_a_byte_order_mark_before_front_matter(tmp_path):
    f = tmp_path / "bom.md"
    f.write_bytes("﻿---\nx: simply\n---\nPlain.\n".encode())
    assert lint_paths([f], None) == []


def test_lint_paths_raises_for_a_missing_path(tmp_path):
    with pytest.raises(FileNotFoundError):
        lint_paths([tmp_path / "missing.md"], None)


def test_scaffold_glossary_writes_the_template_once(tmp_path):
    assert scaffold_glossary(tmp_path) is True
    g = tmp_path / "docs" / "glossary.md"
    assert load_glossary(g)["story"] == "slice"
    g.write_text("custom\n")
    assert scaffold_glossary(tmp_path) is False
    assert g.read_text() == "custom\n"


def test_glossary_template_passes_its_own_lint(plugin_root):
    template = plugin_root / "templates" / "glossary.md"
    assert lint_paths([template], None) == []


def test_inline_code_span_starting_a_line_is_not_a_fence():
    text = ("- the working document's fenced ```` ```harness-decisions ````\n"
            "  (`| id |`) /\n"
            "```` ```harness-abstractions ````\n"
            "  (`| id | kind |`) pipe tables -> the SAME two files.\n"
            "``x`` y.\n")
    assert lint_text(text, "a.md") == []


def test_fence_needs_a_matching_closer_of_at_least_the_same_length():
    text = "````\n```\nutilize\n````\nPlain.\n"
    assert lint_text(text, "a.md") == []
    rows = lint_text("~~~\nx\n```\n", "a.md")
    assert [(r["rule"], r["line"]) for r in rows] == [("unclosed-fence", 1)]


def test_stage_compile_skill_has_no_false_unclosed_fence(plugin_root):
    rows = lint_paths([plugin_root / "skills/architect/stage-compile.md"], None)
    assert "unclosed-fence" not in rules(rows)
