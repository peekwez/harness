"""Spec 5.5: `architect --from-explore` turns frozen cards into ADRs."""

import json

from conftest import run_cli
from explore_samples import DECISIONS, OPEN, VERIFY

from engine.explore import front_matter

ADR = "adr/008-where-do-orders-live.md"   # the toy repo already has adr/007


def _frozen(toy, decisions=DECISIONS):
    assert run_cli("explore", root=toy).returncode == 0
    (toy / "explore" / "DECISIONS.md").write_text(decisions)
    (toy / "explore" / "VERIFY.md").write_text(VERIFY)
    (toy / "explore" / "OPEN.md").write_text(OPEN)
    proc = run_cli("explore", "--freeze", root=toy)
    assert proc.returncode == 0, proc.stdout


def _from_explore(toy, *extra):
    return run_cli("architect", "--from-explore", *extra, root=toy)


def test_one_adr_and_one_row_per_chosen_card(toy):
    _frozen(toy)
    proc = _from_explore(toy)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["adrs"] == [ADR]
    assert out["rows"] == ["D-E1"]
    assert out["parked"] == ["D-E2"]
    assert out["stage"] == 3
    data, body = front_matter((toy / ADR).read_text())
    assert data["id"] == "008"
    assert data["status"] == "accepted"
    assert data["explore_card"] == "D-E1"
    row = data["decision_table_rows"][0]
    assert row["id"] == "D-E1"
    assert row["domain"] == "storage"
    assert row["question"] == "Where do orders live?"
    assert row["answer"].startswith("SQLite file. One file holds all orders.")
    assert row["answer"].endswith(f"Full card: {ADR}.")
    assert len(row["answer"].split()) <= 150
    assert "### D-E1: Where do orders live?" in body
    assert "**Reason:** We have one writer for a year." in body
    assert "D-E2" not in body


def test_working_doc_marks_decided_and_deferred(toy):
    _frozen(toy)
    _from_explore(toy)
    text = (toy / "docs" / "architecture.md").read_text()
    assert text.startswith("# Architecture — seeded from explore/DECISIONS.md")
    assert "<!-- stage: 3 -->" in text
    assert "[constraint] D-E1: Where do orders live?" in text
    assert "Do not ask this again." in text
    assert ("[open-question] D-E2: Which queue do we use? deferred: kwesi "
            "(trigger: more than 1,000 jobs a minute)") in text


def test_seed_compiles_and_passes_the_open_question_check(toy):
    from engine.compiler import author_gate, compile_substrate
    _frozen(toy)
    _from_explore(toy)
    doc = toy / "docs" / "architecture.md"
    report = compile_substrate(toy, working_doc=doc)
    assert "D-E1" in report["decisions"]
    rows = [json.loads(line) for line in
            (toy / ".harness" / "decisions.jsonl").read_text().splitlines()]
    assert {r["id"]: r["adr_ref"] for r in rows}["D-E1"] == ADR
    gaps = author_gate(toy, working_doc=doc)["gaps"]
    assert not any("open question" in g for g in gaps), gaps


def test_from_explore_refuses_when_not_frozen(toy):
    run_cli("explore", root=toy)
    proc = _from_explore(toy)
    assert proc.returncode == 1
    assert "harness explore --freeze" in json.loads(proc.stderr)["error"]
    assert not (toy / "docs" / "architecture.md").exists()


def test_from_explore_refuses_cards_broken_after_freeze(toy):
    _frozen(toy)
    path = toy / "explore" / "DECISIONS.md"
    path.write_text(path.read_text().replace("**Chosen:** A",
                                             "**Chosen:** C"))
    proc = _from_explore(toy)
    assert proc.returncode == 1
    err = json.loads(proc.stderr)["error"]
    assert "is not valid" in err and "'Chosen' is 'C'" in err
    assert not (toy / ADR).exists()


STAGE5_DOC = """# Architecture

<!-- stage: 5 -->

[constraint] Orders are small JSON objects.

```harness-decisions
| id | domain | question | answer | adr_ref | security |
| --- | --- | --- | --- | --- | --- |
| D-100 | config | Where do defaults live? | In config.yaml, never in code. | adr/007-telemetry.md | |
| D-101 | component | How are handlers named? | verb_noun. | | |
```
"""


def _stage5_doc(toy):
    doc = toy / "docs" / "architecture.md"
    doc.parent.mkdir(exist_ok=True)
    doc.write_text(STAGE5_DOC)
    return doc


def test_from_explore_appends_cards_to_an_existing_doc(toy):
    doc = _stage5_doc(toy)
    _frozen(toy)
    proc = _from_explore(toy)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["adrs"] == [ADR]
    assert out["stage"] == 5
    assert out["appended"] == ["D-E1", "D-E2"]
    text = doc.read_text()
    assert text.startswith(STAGE5_DOC)
    assert "<!-- stage: 5 -->" in text and "<!-- stage: 3 -->" not in text
    assert "| D-100 | config |" in text
    assert "[constraint] D-E1: Where do orders live?" in text
    assert ("[open-question] D-E2: Which queue do we use? deferred: kwesi "
            "(trigger: more than 1,000 jobs a minute)") in text


def test_append_is_idempotent_per_card_id(toy):
    doc = _stage5_doc(toy)
    _frozen(toy)
    _from_explore(toy)
    before = doc.read_text()
    adr_before = (toy / ADR).read_text()
    proc = _from_explore(toy)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["adrs"] == [] and out["appended"] == []
    assert out["unchanged"] == [ADR]
    assert doc.read_text() == before
    assert (toy / ADR).read_text() == adr_before


def test_appended_doc_compiles_and_passes_author_gate(toy):
    from engine.compiler import author_gate, compile_substrate
    doc = _stage5_doc(toy)
    _frozen(toy)
    _from_explore(toy)
    report = compile_substrate(toy, working_doc=doc)
    assert "D-E1" in report["decisions"] and "D-100" in report["decisions"]
    gate = author_gate(toy, working_doc=doc)
    assert gate["passed"], gate["gaps"]


def test_append_refuses_before_any_write(toy):
    doc = _stage5_doc(toy)
    _frozen(toy)
    path = toy / "explore" / "DECISIONS.md"
    path.write_text(path.read_text().replace("one writer", "two writers"))
    assert _from_explore(toy).returncode == 1
    assert doc.read_text() == STAGE5_DOC
    assert not (toy / ADR).exists()


def test_from_explore_is_idempotent_with_force(toy):
    _frozen(toy)
    _from_explore(toy)
    out = json.loads(_from_explore(toy, "--force").stdout)
    assert out["adrs"] == []
    assert out["unchanged"] == [ADR]
    assert sorted(p.name for p in (toy / "adr").glob("*.md")) == [
        "007-telemetry.md", "008-where-do-orders-live.md"]


def test_from_explore_refuses_to_rewrite_a_changed_adr(toy):
    _frozen(toy)
    _from_explore(toy)
    path = toy / "explore" / "DECISIONS.md"
    path.write_text(path.read_text().replace(
        "We have one writer for a year.", "One writer for two years."))
    assert run_cli("explore", "--freeze", root=toy).returncode == 0
    proc = _from_explore(toy)
    assert proc.returncode == 1
    assert ADR in json.loads(proc.stderr)["error"]
    assert "One writer for two years." not in (toy / ADR).read_text()


def test_row_answer_over_150_words_fails_loud():
    import pytest
    from explore_samples import CARD

    from engine import HarnessError
    from engine.explore import parse_cards
    from engine.explore_adr import row_answer
    card = parse_cards(CARD)[0]
    card["options"][0]["fields"]["Solves"] = "word " * 160
    with pytest.raises(HarnessError, match="limit is 150"):
        row_answer(card, ADR)


def test_domain_defaults_to_architecture():
    from explore_samples import CARD

    from engine.explore import parse_cards
    from engine.explore_adr import card_domain
    card = parse_cards(CARD.replace("**Domain:** storage\n", ""))[0]
    assert card_domain(card) == "architecture"


def test_from_spec_and_from_explore_are_exclusive(toy):
    proc = run_cli("architect", "--from-spec", "x.md", "--from-explore",
                   root=toy)
    assert proc.returncode == 2


def test_from_explore_refuses_an_edit_after_freeze(toy):
    _frozen(toy)
    path = toy / "explore" / "DECISIONS.md"
    path.write_text(path.read_text().replace(
        "We have one writer for a year.", "One writer for two years."))
    proc = _from_explore(toy)
    assert proc.returncode == 1
    err = json.loads(proc.stderr)["error"]
    assert "changed after freeze" in err
    assert "harness explore --freeze" in err
    assert not (toy / ADR).exists()


def test_refreeze_at_a_new_commit_keeps_adrs_unchanged(toy):
    from conftest import git
    _frozen(toy)
    _from_explore(toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "explore")
    (toy / "docs" / "architecture.md").unlink()
    assert run_cli("explore", "--freeze", root=toy).returncode == 0
    proc = _from_explore(toy)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["unchanged"] == [ADR]


def test_invalid_cards_error_is_short_and_counts_problems(toy):
    _frozen(toy)
    path = toy / "explore" / "DECISIONS.md"
    path.write_text(path.read_text().replace("**Chosen:** A", "**Chosen:** C")
                    .replace("- Solves: Many writers.", ""))
    err = json.loads(_from_explore(toy).stderr)["error"]
    assert "more. Run: harness explore --freeze to list them" in err
    head = err.split(" ...and")[0]
    assert 5 < len(head.split()) <= 25, head
    assert "D-E1" in head and "Solves" in head, head


def test_refreeze_keeps_digest_and_a_body_edit_changes_it(toy):
    _frozen(toy)
    path = toy / "explore" / "DECISIONS.md"
    first = front_matter(path.read_text())[0]["frozen_digest"]
    assert run_cli("explore", "--freeze", root=toy).returncode == 0
    assert front_matter(path.read_text())[0]["frozen_digest"] == first
    path.write_text(path.read_text().replace("one writer", "two writers"))
    assert run_cli("explore", "--freeze", root=toy).returncode == 0
    assert front_matter(path.read_text())[0]["frozen_digest"] != first


def _supersede(toy):
    path = toy / ADR
    path.write_text(path.read_text().replace("status: accepted",
                                             "status: superseded"))


def _edit_card(toy):
    path = toy / "explore" / "DECISIONS.md"
    path.write_text(path.read_text().replace(
        "We have one writer for a year.", "One writer for two years."))
    assert run_cli("explore", "--freeze", root=toy).returncode == 0


def test_superseded_adr_gets_a_new_adr_for_a_changed_card(toy):
    _frozen(toy)
    _from_explore(toy)
    (toy / "docs" / "architecture.md").unlink()
    _supersede(toy)
    _edit_card(toy)
    proc = _from_explore(toy)
    assert proc.returncode == 0, proc.stderr
    new = "adr/009-where-do-orders-live.md"
    assert json.loads(proc.stdout)["adrs"] == [new]
    assert new in (toy / "docs" / "architecture.md").read_text()


def test_force_never_rewrites_a_superseded_adr(toy):
    _frozen(toy)
    _from_explore(toy)
    _supersede(toy)
    before = (toy / ADR).read_text()
    _edit_card(toy)
    assert _from_explore(toy, "--force").returncode == 0
    assert (toy / ADR).read_text() == before


def test_force_refuses_a_non_accepted_adr(toy):
    _frozen(toy)
    _from_explore(toy)
    path = toy / ADR
    path.write_text(path.read_text().replace("status: accepted",
                                             "status: proposed"))
    before = path.read_text()
    _edit_card(toy)
    assert _from_explore(toy, "--force").returncode == 1
    assert path.read_text() == before


def test_refusal_names_the_adr_to_supersede(toy):
    _frozen(toy)
    _from_explore(toy)
    _edit_card(toy)
    err = json.loads(_from_explore(toy).stderr)["error"]
    assert err == (f"architect: {ADR} records a different choice for D-E1. "
                   f"Write an ADR that supersedes it, then run this again.")
    assert len(err.split()) <= 25


def _choose_b(toy):
    path = toy / "explore" / "DECISIONS.md"
    path.write_text(path.read_text().replace("**Chosen:** A",
                                             "**Chosen:** B"))
    assert run_cli("explore", "--freeze", root=toy).returncode == 0


def test_force_never_rewrites_a_changed_accepted_adr(toy):
    _frozen(toy)
    _from_explore(toy)
    before = (toy / ADR).read_bytes()
    _choose_b(toy)
    proc = _from_explore(toy, "--force")
    assert proc.returncode == 1
    assert "records a different choice for D-E1" in \
        json.loads(proc.stderr)["error"]
    assert (toy / ADR).read_bytes() == before


def test_a_superseding_adr_lets_the_new_choice_through(toy):
    _frozen(toy)
    _from_explore(toy)
    before = (toy / ADR).read_bytes()
    _choose_b(toy)
    (toy / "adr" / "009-orders-in-postgres.md").write_text(
        "---\nid: '009'\nstatus: accepted\ndomains: [storage]\n"
        "supersedes: ['008']\ndecision_table_rows: []\nabstractions: []\n"
        "---\n\n# ADR-009: Orders move to Postgres\n")
    proc = _from_explore(toy, "--force")
    assert proc.returncode == 0, proc.stderr
    new = "adr/010-where-do-orders-live.md"
    assert json.loads(proc.stdout)["adrs"] == [new]
    assert "Postgres" in (toy / new).read_text()
    assert (toy / ADR).read_bytes() == before
    assert new in (toy / "docs" / "architecture.md").read_text()


def test_stale_adr_prints_a_check_line(toy):
    _frozen(toy)
    _from_explore(toy)
    path = toy / "explore" / "DECISIONS.md"
    path.write_text(path.read_text().replace(
        "**Chosen:** A", "**Chosen:** parked"))
    (toy / "explore" / "OPEN.md").write_text(
        OPEN + "\n## D-E1: Where do orders live?\n- Owner: kwesi\n"
        "- Trigger: later\n")
    assert run_cli("explore", "--freeze", root=toy).returncode == 0
    proc = _from_explore(toy)
    assert proc.returncode == 0, proc.stderr
    assert f"check: {ADR}" in proc.stderr


def test_two_adrs_for_one_card_are_refused(toy):
    _frozen(toy)
    _from_explore(toy)
    dup = toy / "adr" / "009-copy.md"
    dup.write_text((toy / ADR).read_text().replace("id: '008'", "id: '009'")
                   .replace("id: 008", "id: 009"))
    err = json.loads(_from_explore(toy).stderr)["error"]
    assert "008-where" in err and "009-copy" in err


def test_explore_adr_uses_the_public_out_of_force():
    from engine import compiler
    from engine.context_cost import PLUGIN_ROOT
    assert compiler.out_of_force is compiler._out_of_force
    body = (PLUGIN_ROOT / "engine" / "explore_adr.py").read_text()
    assert "import out_of_force" in body and "_out_of_force" not in body


def test_append_relinks_a_constraint_to_the_superseding_explore_adr(toy):
    doc = _stage5_doc(toy)
    _frozen(toy)
    _from_explore(toy)
    _choose_b(toy)
    (toy / "adr" / "009-orders-in-postgres.md").write_text(
        "---\nid: '009'\nstatus: accepted\ndomains: [storage]\n"
        "supersedes: ['008']\ndecision_table_rows: []\nabstractions: []\n"
        "---\n\n# ADR-009: Orders move to Postgres\n")
    doc.write_text(doc.read_text() + "\nHuman note: see adr/008 history.\n")
    before = doc.read_text().splitlines()
    proc = _from_explore(toy)
    assert proc.returncode == 0, proc.stderr
    new = "adr/010-where-do-orders-live.md"
    out = json.loads(proc.stdout)
    assert out["adrs"] == [new] and out["relinked"] == ["D-E1"]
    after = doc.read_text().splitlines()
    assert len(after) == len(before)
    changed = [(a, b) for a, b in zip(before, after) if a != b]
    assert len(changed) == 1
    old_line, new_line = changed[0]
    assert ADR in old_line and new in new_line
    assert new_line == (f"Decided: Postgres. Card and reason: {new}. "
                        f"Do not ask this again.")
    again = _from_explore(toy)
    assert json.loads(again.stdout)["relinked"] == []
    assert doc.read_text().splitlines() == after
