"""Spec 5.2: the decision card format and its checks."""
import pytest
from explore_samples import CARD, DECISIONS

from engine.explore import (chosen_letter, front_matter, parse_cards,
                            sentence_count, set_front_matter, validate_cards)


def _problems(text):
    return validate_cards(parse_cards(text))


def test_parse_reads_every_field_of_a_card():
    cards = parse_cards("# Decisions\n\n" + CARD)
    assert [c["id"] for c in cards] == ["D-E1"]
    card = cards[0]
    assert card["question"] == "Where do orders live?"
    assert card["line"] == 3
    assert card["fields"]["Domain"] == "storage"
    assert card["fields"]["Chosen"] == "A"
    assert [o["letter"] for o in card["options"]] == ["A", "B"]
    assert card["options"][0]["name"] == "SQLite file"
    assert card["options"][0]["recommended"] is True
    assert card["options"][1]["recommended"] is False
    assert card["options"][1]["fields"]["Undo cost"].startswith("low")
    assert card["raw"].startswith("## D-E1: Where do orders live?")
    assert card["raw"].endswith("**Reason:** We have one writer for a year.")


def test_raw_stops_at_the_next_card():
    cards = parse_cards(DECISIONS)
    assert [c["id"] for c in cards] == ["D-E1", "D-E2"]
    assert "D-E2" not in cards[0]["raw"]
    assert chosen_letter(cards[1]) == "parked"


def test_a_valid_file_has_no_problems():
    assert _problems(DECISIONS) == []


def test_comments_and_front_matter_are_not_read():
    text = ("---\nfrozen_by: x\n---\n# Decisions\n\n<!--\n"
            "## D-E9: <question>\n-->\n" + CARD)
    assert [c["id"] for c in parse_cards(text)] == ["D-E1"]


def test_header_prose_is_not_a_card():
    text = ("# Decisions\n\nMark exactly one option `(recommended)`.\n"
            "Reply with a letter, 'explain more about X', or 'not sure, "
            "park it'.\n\n" + CARD)
    assert [c["id"] for c in parse_cards(text)] == ["D-E1"]
    assert _problems(text) == []


def test_continuation_lines_extend_the_field():
    text = CARD.replace("- Solves: One file holds all orders. No server runs.",
                        "- Solves: One file holds all orders.\n  No server runs.")
    option = parse_cards(text)[0]["options"][0]
    assert option["fields"]["Solves"] == ("One file holds all orders. "
                                          "No server runs.")


def test_missing_evidence_is_a_problem():
    text = CARD.replace("**Evidence:** explore/bench.sh wrote 10,000 orders "
                        "in 2 s on SQLite.\n", "")
    assert any("'Evidence' is missing" in p for p in _problems(text))


def test_no_evidence_needs_a_reason():
    bare = CARD.replace("explore/bench.sh wrote 10,000 orders in 2 s on "
                        "SQLite.", "no evidence")
    assert any("no evidence: <reason>" in p for p in _problems(bare))
    reasoned = CARD.replace("explore/bench.sh wrote 10,000 orders in 2 s on "
                            "SQLite.", "no evidence: the toy has no store.")
    assert _problems(reasoned) == []


def test_three_sentences_in_a_field_is_a_problem():
    text = CARD.replace("- Trade-off: One writer at a time.",
                        "- Trade-off: One writer. No replicas. No failover.")
    assert any("option A: field 'Trade-off' has more than 2 sentences" in p
               for p in _problems(text))


def test_chosen_must_name_an_option_of_the_card_or_parked():
    assert any("'Chosen' is 'C'" in p
               for p in _problems(CARD.replace("**Chosen:** A",
                                               "**Chosen:** C")))
    assert any("'Chosen'" in p
               for p in _problems(CARD.replace("**Chosen:** A",
                                               "**Chosen:** maybe")))
    assert _problems(CARD.replace("**Chosen:** A", "**Chosen:** parked")) == []


@pytest.mark.parametrize("value", ["A, but maybe B", "A or B", "A maybe",
                                   "parked later", "Option", "AB", ""])
def test_a_vague_chosen_is_not_a_choice(value):
    text = CARD.replace("**Chosen:** A", f"**Chosen:** {value}")
    card = parse_cards(text)[0]
    assert chosen_letter(card) is None
    assert any("'Chosen'" in p for p in validate_cards([card]))


@pytest.mark.parametrize("value, letter", [("a", "A"), ("Option B", "B"),
                                           ("option a", "A"), ("PARKED", "parked"),
                                           ("Parked", "parked")])
def test_chosen_forms_that_are_accepted(value, letter):
    text = CARD.replace("**Chosen:** A", f"**Chosen:** {value}")
    card = parse_cards(text)[0]
    assert chosen_letter(card) == letter
    assert validate_cards([card]) == []


def test_exactly_one_option_is_recommended():
    none = CARD.replace(" (recommended)", "")
    assert any("D-E1" in p and "recommended" in p for p in _problems(none))
    two = CARD.replace("### Option B: Postgres",
                       "### Option B: Postgres (recommended)")
    assert any("D-E1" in p and "recommended" in p for p in _problems(two))


@pytest.mark.parametrize("cid", ["D-041", "D-E", "D-Ex", "D-E1-2"])
def test_a_card_id_must_be_d_e_number(cid):
    text = CARD.replace("D-E1", cid)
    problems = _problems(text)
    assert any("D-E<number>" in p for p in problems)


def test_a_misspelled_field_is_named():
    text = CARD.replace("- Trade-off: One writer at a time.",
                        "- Tradeoff: One writer at a time.")
    problems = _problems(text)
    assert any("'Tradeoff' is not a card field" in p for p in problems)
    assert any("option A: field 'Trade-off' is missing" in p
               for p in problems)


def test_undo_cost_needs_a_level_and_a_reason():
    text = CARD.replace("- Undo cost: low, the toy", "- Undo cost: cheap, the toy")
    assert any("must start with low, medium or high" in p
               for p in _problems(text))


def test_a_card_needs_two_options():
    one = CARD.split("### Option B")[0] + (
        "**Would change it:** Load.\n**Chosen:** A\n**Reason:** Fine.\n")
    assert any("two or more options" in p for p in _problems(one))


def test_template_text_is_a_problem():
    text = CARD.replace("**Why now:** The toy needs a store before the second "
                        "feature.", "**Why now:** <one sentence>")
    assert any("template text" in p for p in _problems(text))


def test_no_cards_is_a_problem():
    assert "no decision cards" in validate_cards([])[0]


def test_duplicate_card_ids_are_a_problem():
    assert any("used twice" in p for p in _problems(CARD + "\n" + CARD))


def test_problems_are_short_ste80_lines():
    text = CARD.replace("**Chosen:** A", "**Chosen:** maybe")
    for p in _problems(text) + validate_cards([]):
        assert len(p.split()) <= 25


def test_sentence_count():
    assert sentence_count("One. Two.") == 2
    assert sentence_count("Uses v1.2 of the client.") == 1
    assert sentence_count("") == 0


def test_set_front_matter_keeps_the_body():
    out = set_front_matter("# Decisions\n", {"frozen_by": "t <t@t>"})
    data, body = front_matter(out)
    assert data == {"frozen_by": "t <t@t>"}
    assert body == "# Decisions\n"
    again = set_front_matter(out, {"frozen_at_commit": "abc"})
    assert front_matter(again)[0] == {"frozen_by": "t <t@t>",
                                      "frozen_at_commit": "abc"}


def test_fenced_cards_are_not_read():
    for fence in ("```", "~~~"):
        text = f"# Decisions\n\n{fence}md\n{CARD}{fence}\n\n" + CARD
        cards = parse_cards(text)
        assert [c["id"] for c in cards] == ["D-E1"]
        assert cards[0]["line"] == text.splitlines().index(
            "## D-E1: Where do orders live?", 5) + 1


def test_a_bad_card_heading_is_reported():
    for heading in ("## D-E1 Where do orders live?", "## D-E1:"):
        text = CARD.replace("## D-E1: Where do orders live?", heading)
        problems = _problems(text)
        assert any("D-E1 line 1" in p and "## D-E1: <question>" in p
                   for p in problems), problems


def test_a_bad_option_heading_is_reported_and_does_not_leak():
    text = CARD.replace("### Option B: Postgres", "### Option b - Postgres")
    cards = parse_cards(text)
    assert [o["letter"] for o in cards[0]["options"]] == ["A"]
    assert "Solves" in cards[0]["options"][0]["fields"]
    assert cards[0]["options"][0]["fields"]["Solves"].startswith("One file")
    problems = validate_cards(cards)
    assert any("option heading" in p and "### Option A: <name>" in p
               for p in problems)


def test_a_repeated_field_is_reported():
    card_dup = CARD.replace("**Domain:** storage",
                            "**Domain:** storage\n**Domain:** other")
    assert any("field 'Domain' appears twice" in p for p in _problems(card_dup))
    opt_dup = CARD.replace("- Trade-off: One writer at a time.",
                           "- Trade-off: One writer at a time.\n"
                           "- Trade-off: Again.")
    assert any("D-E1 option A: field 'Trade-off' appears twice" in p
               for p in _problems(opt_dup))


def test_long_values_are_clipped_in_problems():
    long = " ".join(["word"] * 40)
    for text in (CARD.replace("**Chosen:** A", f"**Chosen:** {long}"),
                 CARD.replace("**Domain:** storage", f"**{long}:** x")):
        problems = _problems(text)
        assert problems
        assert all(len(p.split()) <= 25 for p in problems)


def test_an_unclosed_fence_is_reported_and_later_cards_still_parse():
    text = ("# Decisions\n\n" + CARD + "\n```\n\n"
            + CARD.replace("D-E1", "D-E2"))
    cards = parse_cards(text)
    assert [c["id"] for c in cards] == ["D-E1", "D-E2"]
    line = text.splitlines().index("```") + 1
    problems = validate_cards(cards)
    assert [p for p in problems if "fence" in p] == [
        f"Line {line}: a code fence opens here and never closes. "
        "Close it with ```."]
    assert len(problems[0].split()) <= 25


def test_a_closing_fence_must_match_the_opener():
    # ```` opened, ``` does not close it, so the fence stays open.
    text = "````\n```\n" + CARD
    assert any("never closes" in p for p in _problems(text))
    # ~~~ does not close ```; a bare ``` does.
    assert parse_cards("```\n~~~\n" + CARD) and any(
        "never closes" in p for p in _problems("```\n~~~\n" + CARD))
    assert not any("never closes" in p
                   for p in _problems("```\n" + CARD + "```\n" + CARD))
    # An info string cannot close a fence.
    assert any("never closes" in p
               for p in _problems("```\n```md\n" + CARD))
