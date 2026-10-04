"""Issue #2: the explore skill, and the card format in architect and review."""
import json
import re

from conftest import PLUGIN_ROOT

from engine.explore import (CARD_FIELDS, OPTION_FIELDS, check_statements,
                            parse_cards, parse_open, validate_cards)

SKILL = PLUGIN_ROOT / "skills" / "explore"
KEPT = {"explore", "architect", "design-review", "adr-authoring",
        "verification", "backlog", "build", "review", "close-slice", "init",
        "harness"}
INVITE = ("End each card you show with: Reply with a letter, "
          "'explain more about X', or 'not sure, park it'.")
CALIBRATE = "calibrate before the first card when explore did not run"
VERIFY_RULE = ("When `explore/VERIFY.md` exists, write every statement "
               "there; compile does not read the working document then")


def _read(rel):
    return (PLUGIN_ROOT / rel).read_text()


def _flat(text):
    """Joins wrapped lines so that a phrase can span a line break."""
    return re.sub(r"\s+", " ", text)


def test_eleven_skills_including_explore():
    names = {p.name for p in (PLUGIN_ROOT / "skills").iterdir()
             if (p / "SKILL.md").is_file()}
    assert names == KEPT


def test_explore_skill_has_the_seven_steps_in_order():
    body = (SKILL / "SKILL.md").read_text()
    assert body.startswith("---\nname: explore\n")
    steps = ["**Calibrate.**", "**Frame.**", "**Toy.**", "**Cards.**",
             "**Verify list.**", "**Challenge.**", "**Freeze.**"]
    positions = [body.index(s) for s in steps]
    assert positions == sorted(positions)
    assert "harness explore --freeze" in body
    assert "harness architect --from-explore" in body


def test_explore_skill_states_the_option_and_answer_rules():
    body = (SKILL / "SKILL.md").read_text()
    for text in ("what it solves with an example", "the trade-off",
                 "the 1st, 2nd and 3rd order effects", "the undo cost",
                 '"explain more about X"', '"not sure, park it"',
                 "A vague reply is not a choice", "explore/OPEN.md",
                 "calibrate.md"):
        assert text in body, text


def test_explore_skill_names_the_contract_seam():
    """W6-P16: the carried 'contract as seam' card topic."""
    for rel in ("SKILL.md", "card.md"):
        body = _flat((SKILL / rel).read_text())
        assert "contract" in body, rel
        assert "../architect/coverage-map.md" in body, rel


def test_explore_skill_has_the_codex_preamble():
    """W6-P20: Codex resolves the plugin root as architect says."""
    body = _flat((SKILL / "SKILL.md").read_text())
    assert "In Codex, resolve the plugin root" in body


def test_plugin_listing_names_explore_and_the_new_gates():
    """W6-P20."""
    plugin = json.loads(_read(".claude-plugin/marketplace.json"))["plugins"][0]
    desc = plugin["description"]
    for text in ("explore", "G9", "G10"):
        assert text in desc, text


def test_card_reference_names_every_field():
    body = (SKILL / "card.md").read_text()
    for name in CARD_FIELDS + OPTION_FIELDS:
        assert name in body, name


def test_card_reference_example_is_a_valid_card():
    body = (SKILL / "card.md").read_text()
    blocks = re.findall(r"```markdown\n(.*?)```", body, re.S)
    example = next(b for b in blocks if "D-E1: Where do orders live?" in b)
    cards = parse_cards(example)
    assert [c["id"] for c in cards] == ["D-E1"]
    assert validate_cards(cards) == []


def test_calibrate_names_the_three_levels_and_memory_rule():
    body = (SKILL / "calibrate.md").read_text()
    for text in ("new to it", "used it", "designed it", "personal memory",
                 "Harness does not store them"):
        assert text in body, text


def test_calibrate_keeps_every_field_at_every_level():
    """Skill level changes the depth, never the fields."""
    body = _flat((SKILL / "calibrate.md").read_text())
    for text in ("vocabulary", "examples", "1st, 2nd and 3rd order effects",
                 "every field"):
        assert text in body, text


def test_cards_end_with_the_invitation():
    """W6-P10: every card the human sees invites the three answers."""
    for rel in ("skills/explore/SKILL.md", "skills/explore/card.md",
                "agents/architect.md"):
        assert INVITE in _flat(_read(rel)), rel


def test_architect_paths_calibrate_when_explore_did_not_run():
    """W6-P10: the skip and spec paths still adapt depth."""
    for rel in ("agents/architect.md", "skills/architect/stage-brainstorm.md",
                "skills/architect/stage-converge.md"):
        body = _flat(_read(rel))
        assert "calibrate.md" in body, rel
        assert CALIBRATE in body, rel


def test_statements_go_to_verify_md_after_explore():
    """W6-P23: compile reads explore/VERIFY.md first."""
    for rel in ("skills/explore/SKILL.md", "skills/explore/card.md",
                "agents/architect.md"):
        assert VERIFY_RULE in _flat(_read(rel)), rel


def test_templates_contain_no_live_cards_or_statements():
    t = PLUGIN_ROOT / "templates" / "explore"
    assert parse_cards((t / "DECISIONS.md").read_text()) == []
    statements, problems = check_statements((t / "VERIFY.md").read_text())
    assert statements == []
    assert len(problems) == 1 and "no statements" in problems[0]
    assert parse_open((t / "OPEN.md").read_text()) == {}


def test_architect_skill_names_the_three_sources_and_the_card():
    body = _flat(_read("skills/architect/SKILL.md"))
    for text in ("--from-explore", "--from-spec", "--skip-explore",
                 "refuses to start", "../explore/card.md"):
        assert text in body, text
    assert "create it if missing" not in body
    assert ("A source command creates it: `--from-explore`, `--from-spec` "
            "or `--skip-explore`.") in body
    assert "../explore/card.md" in _read("skills/architect/stage-converge.md")
    assert "--skip-explore" in _read("skills/architect/stage-brainstorm.md")


def test_brainstorm_uses_cards_instead_of_refusing_to_solution():
    """W6-P9: the stage-1 rule is the decision-card rule."""
    body = _flat(_read("skills/architect/stage-brainstorm.md"))
    assert "No solutioning" not in body
    assert "decision card" in body
    assert "superpowers:brainstorming" in body


def test_converge_keeps_delegation_as_an_explicit_choice():
    """W6-P8: "you choose" picks the recommended option, on the record."""
    body = _flat(_read("skills/architect/stage-converge.md"))
    for text in ('"you choose"', "recommended option",
                 "delegated: <their words>", "confirm"):
        assert text in body, text


def test_design_review_attacks_the_cards():
    body = _read("skills/design-review/SKILL.md")
    assert "Would change it" in body
    assert "../explore/card.md" in body


def test_architect_agent_uses_cards_and_never_refuses_to_solution():
    body = _read("agents/architect.md")
    assert "refuses to solution" not in body
    assert "do not solution" not in body.lower()
    for text in ("decision card", "skills/explore/card.md",
                 '"explain more about X"', '"not sure, park it"',
                 "--from-explore", "--skip-explore"):
        assert text in body, text


def test_architect_agent_keeps_the_w2_duties():
    """W6-P7: extend the agent; keep the W2 duties."""
    body = _flat(_read("agents/architect.md"))
    for text in ("coverage map", "Scope assessment", "premortem.md",
                 "verification/design.md", "harness:design-review",
                 "input hashes", "two-round budget", "human final signoff",
                 "Codex"):
        assert text in body, text


def test_agents_md_workflow_names_explore_before_architect():
    body = _read("templates/agents-md.md")
    assert "explore -> architect" in body
    assert len(body.splitlines()) <= 50


def test_explore_skill_text_passes_lint_text():
    from engine.lint_text import lint_paths
    paths = sorted(SKILL.glob("*.md")) + [PLUGIN_ROOT / "agents" /
                                         "architect.md"]
    assert lint_paths(paths, PLUGIN_ROOT / "templates" / "glossary.md") == []


FROM_EXPLORE_FIRST = ("If explore/ is frozen and its cards have no ADR yet, "
                      "run `harness architect --from-explore` first, even "
                      "when the working document exists; it adds the cards "
                      "and keeps your stage.")


def test_resume_rule_runs_from_explore_first_for_new_cards():
    for rel in ("skills/architect/SKILL.md", "agents/architect.md"):
        body = _flat(_read(rel))
        assert FROM_EXPLORE_FIRST in body, rel
        assert "resume at its stage marker" in body, rel


def test_architect_skill_names_all_three_seed_commands():
    body = _flat(_read("skills/architect/SKILL.md"))
    assert ("The source commands `architect --from-explore`, `--from-spec` "
            "and `--skip-explore` seed a document") in body
    assert "use --force to rewrite" not in body


def test_multiple_choice_is_for_ordinary_questions_only():
    for rel in ("agents/architect.md", "skills/architect/stage-brainstorm.md"):
        body = _flat(_read(rel))
        assert "Ordinary questions are multiple choice" in body, rel
        assert "Big decisions use the decision card" in body, rel


def test_agent_reuses_explore_skill_levels():
    body = _flat(_read("agents/architect.md"))
    assert ("After `--from-explore`, reuse the skill levels gauged during "
            "explore. Do not calibrate again.") in body


def test_brainstorm_says_where_skip_path_cards_live():
    body = _flat(_read("skills/architect/stage-brainstorm.md"))
    assert ("On the skip or spec path, write each card in the working "
            "document under its `[open-question]` block") in body
