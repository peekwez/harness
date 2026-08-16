"""ADR-002 / D-013 acceptance: `harness architect --from-spec <path>` seeds
the Phase-0 working document from an existing spec at `<!-- stage: 3 -->`.

A repo that already has a 1000-line spec must not be re-derived Socratically:
headings become `[constraint]` blocks, TODO/TBD/Open lines become
`[open-question]` blocks, and the doc ends with an empty
```harness-decisions` table for the human to fill in the same file.
"""
import json

from conftest import run_cli

SPEC = """# Kente Platform Spec

Intro prose that belongs to no section.

## Packaging

One distribution per subpackage; PEP 420 namespace packages, Google style.

TODO: decide the version scheme.

### Telemetry

Null-by-default: the base install carries the API only.

## Deferred

- TBD: which backends ship first?
- open: who owns retention?

## Naming
## Layout

Src layout, hatchling, uv workspace.
"""


def _write_spec(toy, body=SPEC):
    spec = toy / "docs" / "spec.md"
    spec.parent.mkdir(exist_ok=True)
    spec.write_text(body)
    return spec


def _seed(toy, *extra, spec_body=SPEC):
    _write_spec(toy, spec_body)
    proc = run_cli("architect", "--from-spec", "docs/spec.md", *extra, root=toy)
    return proc


# ---------------------------------------------------------------- happy path
def test_from_spec_writes_the_working_doc_at_stage_3(toy):
    proc = _seed(toy)
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    doc = toy / "docs" / "architecture.md"
    assert doc.exists()
    assert report["doc"].endswith("docs/architecture.md")
    text = doc.read_text()
    assert text.splitlines()[0] == "# Architecture — seeded from docs/spec.md"
    assert "<!-- stage: 3 -->" in text


def test_every_heading_becomes_a_constraint_block(toy):
    _seed(toy)
    text = (toy / "docs" / "architecture.md").read_text()
    blocks = [ln for ln in text.splitlines() if ln.startswith("[constraint] ")]
    assert blocks == ["[constraint] Packaging", "[constraint] Telemetry",
                      "[constraint] Deferred", "[constraint] Naming",
                      "[constraint] Layout"]
    assert ("[constraint] Packaging\nOne distribution per subpackage; PEP 420 "
            "namespace packages, Google style.") in text
    # the level-1 title is the document's own heading, not a constraint
    assert "[constraint] Kente Platform Spec" not in text


def test_heading_without_a_paragraph_gets_no_summary(toy):
    _seed(toy)
    text = (toy / "docs" / "architecture.md").read_text()
    assert "[constraint] Naming\n(no summary)" in text


def test_todo_tbd_and_open_lines_become_open_questions(toy):
    _seed(toy)
    text = (toy / "docs" / "architecture.md").read_text()
    questions = [ln for ln in text.splitlines()
                 if ln.startswith("[open-question] ")]
    assert questions == [
        "[open-question] TODO: decide the version scheme.",
        "[open-question] TBD: which backends ship first?",
        "[open-question] open: who owns retention?"]


def test_doc_ends_with_an_empty_decisions_table(toy):
    _seed(toy)
    lines = (toy / "docs" / "architecture.md").read_text().rstrip().splitlines()
    assert lines[-4] == "```harness-decisions"
    assert lines[-3] == "| id | domain | question | answer | adr_ref | security |"
    assert lines[-2] == "| --- | --- | --- | --- | --- | --- |"
    assert lines[-1] == "```"


def test_seeded_doc_compiles_and_the_gate_sees_the_open_questions(toy):
    """Round trip: the seed is real substrate input, not a decoration."""
    from engine.compiler import author_gate, compile_substrate
    _seed(toy)
    doc = toy / "docs" / "architecture.md"
    report = compile_substrate(toy, working_doc=doc)
    assert report["decisions"] == ["D-041"]      # the empty table adds none
    gaps = author_gate(toy, working_doc=doc)["gaps"]
    assert sum("open question" in g for g in gaps) == 3


def test_from_spec_accepts_an_explicit_doc_path(toy):
    proc = _seed(toy, "--doc", "docs/design.md")
    assert proc.returncode == 0, proc.stderr
    assert (toy / "docs" / "design.md").exists()
    assert not (toy / "docs" / "architecture.md").exists()


# ---------------------------------------------------------------- fail closed
def test_refuses_to_overwrite_an_existing_doc_without_force(toy):
    doc = toy / "docs" / "architecture.md"
    doc.parent.mkdir(exist_ok=True)
    doc.write_text("hand-written architecture\n")
    proc = _seed(toy)
    assert proc.returncode == 1
    assert doc.read_text() == "hand-written architecture\n"
    err = json.loads(proc.stderr)["error"]
    assert "--force" in err and "architecture.md" in err


def test_force_overwrites(toy):
    doc = toy / "docs" / "architecture.md"
    doc.parent.mkdir(exist_ok=True)
    doc.write_text("hand-written architecture\n")
    proc = _seed(toy, "--force")
    assert proc.returncode == 0, proc.stderr
    assert "<!-- stage: 3 -->" in doc.read_text()


def test_missing_spec_fails_loud(toy):
    proc = run_cli("architect", "--from-spec", "docs/nope.md", root=toy)
    assert proc.returncode == 1
    assert "docs/nope.md" in json.loads(proc.stderr)["error"]


def test_seed_doc_from_spec_is_importable_and_pure():
    from engine.compiler import seed_doc_from_spec
    out = seed_doc_from_spec("## A\n\nfirst para.\n", "docs/spec.md")
    assert out.startswith("# Architecture — seeded from docs/spec.md")
    assert "[constraint] A\nfirst para." in out


def test_architect_is_registered_in_the_command_table():
    from engine.cli import COMMANDS
    assert "architect" in COMMANDS


def test_spec_that_is_a_directory_fails_loud(toy):
    proc = run_cli("architect", "--from-spec", "adr", root=toy)
    assert proc.returncode == 1
    assert "adr" in json.loads(proc.stderr)["error"]
