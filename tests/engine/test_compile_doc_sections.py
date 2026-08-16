"""ADR-002 / D-013 acceptance: decision rows and abstractions may be authored
in `docs/architecture.md` inside fenced ```harness-decisions` /
```harness-abstractions` pipe tables, not only in ADR frontmatter.

The compiler merges them with the ADR-sourced rows; an id claimed by both
sources is a hard error naming both, and a malformed row names the doc path
and the line. A doc with no fenced blocks compiles exactly as it did before.
"""
import pytest
from conftest import run_cli

from engine import HarnessError, read_jsonl
from engine.compiler import author_gate, compile_substrate, parse_doc_blocks

DOC = """# Architecture

Prose is for extrapolation; the compiled form is what gates read.

```harness-decisions
| id | domain | question | answer | adr_ref | security |
| --- | --- | --- | --- | --- | --- |
| D-100 | config | Where do defaults live? | In config.yaml, never in code. | adr/007-telemetry.md | |
| D-101 | component | How are handlers named? | verb_noun. | | true |
```

```harness-abstractions
| id | kind | guidance_ref |
| --- | --- | --- |
| orders | component | docs/architecture.md |
```
"""


def _write_doc(toy, body=DOC):
    doc = toy / "docs" / "architecture.md"
    doc.parent.mkdir(exist_ok=True)
    doc.write_text(body)
    return doc


# ---------------------------------------------------------------- parser
def test_parse_doc_blocks_reads_both_tables():
    blocks = parse_doc_blocks(DOC, source="docs/architecture.md")
    assert [d["id"] for d in blocks["decisions"]] == ["D-100", "D-101"]
    assert blocks["decisions"][0]["domain"] == "config"
    assert blocks["decisions"][0]["adr_ref"] == "adr/007-telemetry.md"
    assert blocks["decisions"][0]["security"] is False
    assert blocks["decisions"][1]["adr_ref"] is None      # empty cell -> null
    assert blocks["decisions"][1]["security"] is True
    assert blocks["abstractions"] == [
        {"id": "orders", "kind": "component",
         "guidance_ref": "docs/architecture.md"}]


def test_parse_doc_blocks_on_a_doc_without_fences_is_empty():
    assert parse_doc_blocks("# Architecture\n\nJust prose.\n") == \
        {"decisions": [], "abstractions": []}


def test_fenced_tables_inside_a_plain_code_block_are_prose():
    """A doc that DOCUMENTS the table syntax must not compile the example."""
    text = ("# Architecture\n\n"
            "````\n"
            "```harness-decisions\n"
            "| id | domain | question | answer | adr_ref | security |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| D-999 | config | q | a | | |\n"
            "```\n"
            "````\n")
    assert parse_doc_blocks(text)["decisions"] == []


# ---------------------------------------------------------------- compile
def test_doc_decision_rows_compile_with_phase0_origin(toy):
    doc = _write_doc(toy)
    report = compile_substrate(toy, working_doc=doc)
    assert "D-100" in report["decisions"] and "D-101" in report["decisions"]
    rows = {d["id"]: d for d in read_jsonl(toy / ".harness" / "decisions.jsonl")}
    assert rows["D-100"]["origin"] == "phase0"
    assert rows["D-100"]["domain"] == "config"
    assert rows["D-100"]["adr_ref"] == "adr/007-telemetry.md"
    assert rows["D-100"]["created"]
    assert rows["D-101"]["adr_ref"] is None
    assert rows["D-101"]["security"] is True
    assert "security" not in rows["D-100"]
    # the ADR-sourced row still compiles alongside
    assert rows["D-041"]["adr_ref"] == "adr/007-telemetry.md"


def test_doc_abstraction_compiles_into_the_registry(toy):
    doc = _write_doc(toy)
    compile_substrate(toy, working_doc=doc)
    entries = {e["id"]: e for e in read_jsonl(toy / ".harness" / "registry.jsonl")}
    assert entries["orders"]["kind"] == "component"
    assert entries["orders"]["status"] == "planned"
    assert "docs/architecture.md" in entries["orders"]["guidance_refs"]


def test_doc_abstraction_with_unknown_kind_is_coerced_and_warned(toy):
    doc = _write_doc(toy, DOC.replace("| orders | component |",
                                      "| ledger | package |"))
    report = compile_substrate(toy, working_doc=doc)
    entries = {e["id"]: e for e in read_jsonl(toy / ".harness" / "registry.jsonl")}
    assert entries["ledger"]["kind"] == "other"
    assert entries["ledger"]["domain"] == "package"
    assert any("ledger" in w and "package" in w for w in report["warnings"])


def test_doc_sourced_compile_is_idempotent(toy):
    doc = _write_doc(toy)
    compile_substrate(toy, working_doc=doc)
    first = (toy / ".harness" / "decisions.jsonl").read_bytes()
    firstr = (toy / ".harness" / "registry.jsonl").read_bytes()
    compile_substrate(toy, working_doc=doc)
    assert (toy / ".harness" / "decisions.jsonl").read_bytes() == first
    assert (toy / ".harness" / "registry.jsonl").read_bytes() == firstr


def test_adjudicated_rows_still_outrank_doc_rows(toy):
    from engine import write_jsonl
    write_jsonl(toy / ".harness" / "decisions.jsonl", [
        {"id": "D-100", "domain": "config", "question": "Where?",
         "answer": "ADJUDICATED ANSWER", "adr_ref": None,
         "origin": "adjudication", "created": "2026-01-02T00:00:00+00:00"}])
    compile_substrate(toy, working_doc=_write_doc(toy))
    rows = {d["id"]: d for d in read_jsonl(toy / ".harness" / "decisions.jsonl")}
    assert rows["D-100"]["answer"] == "ADJUDICATED ANSWER"


def test_doc_without_fenced_blocks_compiles_exactly_as_before(toy):
    """Backward compatibility: the pre-D-013 doc path is untouched."""
    compile_substrate(toy)
    baseline = (toy / ".harness" / "decisions.jsonl").read_bytes()
    doc = _write_doc(toy, "# Architecture\n\nNo typed blocks here at all.\n")
    compile_substrate(toy, working_doc=doc)
    assert (toy / ".harness" / "decisions.jsonl").read_bytes() == baseline


# ---------------------------------------------------------------- fail closed
def test_id_claimed_by_both_an_adr_and_the_doc_is_a_hard_error(toy):
    doc = _write_doc(toy, DOC.replace("| D-100 |", "| D-041 |"))
    with pytest.raises(HarnessError) as exc:
        compile_substrate(toy, working_doc=doc)
    msg = str(exc.value)
    assert "D-041" in msg
    assert "adr/007-telemetry.md" in msg and "docs/architecture.md" in msg


def test_abstraction_claimed_by_both_sources_is_a_hard_error(toy):
    doc = _write_doc(toy, DOC.replace("| orders | component |",
                                      "| telemetry | telemetry |"))
    with pytest.raises(HarnessError) as exc:
        compile_substrate(toy, working_doc=doc)
    assert "telemetry" in str(exc.value)
    assert "adr/007-telemetry.md" in str(exc.value)


def test_wrong_column_count_names_the_doc_and_the_line(toy):
    doc = _write_doc(toy, DOC.replace(
        "| D-101 | component | How are handlers named? | verb_noun. | | true |",
        "| D-101 | component | verb_noun. |"))
    with pytest.raises(HarnessError) as exc:
        compile_substrate(toy, working_doc=doc)
    msg = str(exc.value)
    assert "docs/architecture.md" in msg and ":9" in msg
    assert "\\|" in msg          # names the escape for a literal pipe


def test_row_missing_a_required_field_fails_loud(toy):
    doc = _write_doc(toy, DOC.replace("| D-101 | component |", "| D-101 |  |"))
    with pytest.raises(HarnessError, match="missing 'domain'"):
        compile_substrate(toy, working_doc=doc)


def test_row_missing_an_id_fails_loud(toy):
    doc = _write_doc(toy, DOC.replace("| D-101 | component |", "|  | component |"))
    with pytest.raises(HarnessError, match="missing 'id'"):
        compile_substrate(toy, working_doc=doc)


def test_an_all_empty_row_is_malformed_not_a_separator(toy):
    """`all()` over an empty generator is True — an empty row must not slip
    through the separator check and become a `{"id": "", ...}` row."""
    doc = _write_doc(toy, DOC.replace(
        "| D-101 | component | How are handlers named? | verb_noun. | | true |",
        "|  |  |  |  |  |  |"))
    with pytest.raises(HarnessError, match="missing 'id'"):
        compile_substrate(toy, working_doc=doc)


@pytest.mark.parametrize("sep", ["|-|-|-|-|-|-|", "|:-:|:-:|:-:|:-:|:-:|:-:|",
                                 "| - | - | - | - | - | - |"])
def test_single_dash_separator_rows_are_separators(toy, sep):
    """GFM allows one dash per column: `|-|-|...|` is the alignment row, not
    a decision whose every field is '-'."""
    doc = _write_doc(toy, DOC.replace(
        "| --- | --- | --- | --- | --- | --- |", sep))
    compile_substrate(toy, working_doc=doc)
    rows = {d["id"]: d for d in read_jsonl(toy / ".harness" / "decisions.jsonl")}
    assert "-" not in rows and ":-:" not in rows
    assert set(rows) == {"D-041", "D-100", "D-101"}


def test_a_non_table_line_inside_a_block_names_the_pipe_requirement(toy):
    doc = _write_doc(toy, DOC.replace(
        "| D-101 | component | How are handlers named? | verb_noun. | | true |",
        "D-101, component, verb_noun."))
    with pytest.raises(HarnessError, match=r"must start with"):
        compile_substrate(toy, working_doc=doc)


def test_duplicate_id_inside_the_doc_fails_loud(toy):
    doc = _write_doc(toy, DOC.replace("| D-101 |", "| D-100 |"))
    with pytest.raises(HarnessError, match="D-100"):
        compile_substrate(toy, working_doc=doc)


def test_unterminated_fenced_block_fails_loud(toy):
    doc = _write_doc(toy, DOC.replace("| orders | component | docs/architecture.md |\n```\n",
                                      "| orders | component | docs/architecture.md |\n"))
    with pytest.raises(HarnessError, match="docs/architecture.md"):
        compile_substrate(toy, working_doc=doc)


# ---------------------------------------------------------------- author-gate
def test_doc_only_substrate_needs_no_adr_at_all(tmp_path):
    """The D-013 point: a repo may author Phase 0 entirely in the document."""
    root = tmp_path / "docs-only"
    (root / "docs").mkdir(parents=True)
    doc = root / "docs" / "architecture.md"
    doc.write_text(DOC)
    report = compile_substrate(root, working_doc=doc)
    assert report["adrs"] == []
    assert sorted(report["decisions"]) == ["D-100", "D-101"]
    assert report["registry"] == ["orders"]
    assert author_gate(root, working_doc=doc)["passed"]



def test_author_gate_passes_on_doc_only_substrate(toy):
    """Every sliceable domain covered by rows the human wrote in the doc."""
    doc = _write_doc(toy)
    compile_substrate(toy, working_doc=doc)
    result = author_gate(toy, working_doc=doc)
    assert result["passed"], result["gaps"]


# ---------------------------------------------------------------- bare compile
def test_bare_compile_warns_that_doc_rows_are_ignored(toy):
    """Silent degradation: `compile` without --doc compiled zero doc rows and
    said nothing. Behaviour is unchanged; the omission is now audible."""
    _write_doc(toy)
    proc = run_cli("compile", root=toy)
    assert proc.returncode == 0
    assert "--doc" in proc.stderr and "docs/architecture.md" in proc.stderr
    rows = {d["id"] for d in read_jsonl(toy / ".harness" / "decisions.jsonl")}
    assert "D-100" not in rows          # unchanged: the flag still decides


def test_bare_compile_is_silent_when_the_doc_has_no_typed_blocks(toy):
    _write_doc(toy, "# Architecture\n\nProse only, no typed blocks.\n")
    assert run_cli("compile", root=toy).stderr == ""


def test_compile_with_the_doc_does_not_warn(toy):
    doc = _write_doc(toy)
    assert "--doc" not in run_cli("compile", "--doc", str(doc), root=toy).stderr
