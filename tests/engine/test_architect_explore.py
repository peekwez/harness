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


def test_from_explore_refuses_an_existing_doc_without_force(toy):
    _frozen(toy)
    doc = toy / "docs" / "architecture.md"
    doc.parent.mkdir(exist_ok=True)
    doc.write_text("hand-written\n")
    proc = _from_explore(toy)
    assert proc.returncode == 1
    assert "--force" in json.loads(proc.stderr)["error"]
    assert doc.read_text() == "hand-written\n"
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
    (toy / "docs" / "architecture.md").unlink()
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
    (toy / "docs" / "architecture.md").unlink()
    _edit_card(toy)
    err = json.loads(_from_explore(toy).stderr)["error"]
    assert f"supersedes {ADR}" in err and "--force" in err


def test_stale_adr_prints_a_check_line(toy):
    _frozen(toy)
    _from_explore(toy)
    (toy / "docs" / "architecture.md").unlink()
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
    (toy / "docs" / "architecture.md").unlink()
    err = json.loads(_from_explore(toy).stderr)["error"]
    assert "008-where" in err and "009-copy" in err
