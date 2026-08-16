"""ADR-002 / D-014 acceptance: harness owns the outer loop, superpowers owns
the inner loop, and the working agreement says so in one place. Two failure
modes are cheap to introduce and expensive to debug — a precedence section
that quietly disappears from the generated AGENTS.md, and prose that tells an
agent to invoke a `superpowers:` skill that does not exist (the host silently
does nothing, and the inner loop is skipped)."""
import re

import yaml

from conftest import PLUGIN_ROOT

PRECEDENCE_HEADING = "## Precedence when superpowers is installed"

# superpowers 6.3.0 skill names. Nothing outside this set may be referenced.
SUPERPOWERS_SKILLS = {
    "brainstorming",
    "writing-plans",
    "executing-plans",
    "subagent-driven-development",
    "test-driven-development",
    "systematic-debugging",
    "using-git-worktrees",
    "requesting-code-review",
    "receiving-code-review",
    "verification-before-completion",
    "finishing-a-development-branch",
}

MENTION = re.compile(r"superpowers:([a-z][a-z0-9-]*)")
TEXT_SUFFIXES = {".md", ".sh", ".py", ".json", ".yml", ".yaml", ".jsonl"}


def _prose_files():
    for sub in ("skills", "agents", "templates"):
        for path in sorted((PLUGIN_ROOT / sub).rglob("*")):
            if path.is_file() and path.suffix in TEXT_SUFFIXES \
                    and "__pycache__" not in path.parts:
                yield path
    yield PLUGIN_ROOT / "README.md"


def _norm(text):
    return " ".join(text.split())


def test_agents_md_template_carries_the_precedence_section():
    body = (PLUGIN_ROOT / "templates" / "agents-md.md").read_text()
    assert PRECEDENCE_HEADING in body, (
        "the generated AGENTS.md is the one file both plugins' agents read; "
        f"it must carry the section {PRECEDENCE_HEADING!r}")


def test_precedence_section_states_the_d014_decision_verbatim():
    """The working agreement must not paraphrase the decision row — a
    paraphrase is how the two plugins drift back into contradiction."""
    adr = (PLUGIN_ROOT / "adr"
           / "002-kente-capable-superpowers-composable.md").read_text()
    front = yaml.safe_load(adr.split("---", 2)[1])
    d014 = next(r for r in front["decision_table_rows"] if r["id"] == "D-014")
    template = (PLUGIN_ROOT / "templates" / "agents-md.md").read_text()
    assert _norm(d014["answer"]) in _norm(template), \
        "templates/agents-md.md must quote the D-014 answer verbatim"


def test_every_superpowers_skill_reference_names_a_real_skill():
    offenders = []
    for path in _prose_files():
        for i, line in enumerate(path.read_text().splitlines(), 1):
            for name in MENTION.findall(line):
                if name not in SUPERPOWERS_SKILLS:
                    offenders.append(
                        f"{path.relative_to(PLUGIN_ROOT)}:{i}: "
                        f"superpowers:{name}")
    assert not offenders, (
        "these reference a skill superpowers 6.3.0 does not ship — the host "
        "silently no-ops and the inner loop is skipped:\n"
        + "\n".join(offenders))


def test_the_composition_is_actually_wired_into_the_loop_skills():
    """D-014 is only real if the skills an agent actually reads name the
    inner-loop skills at the points they apply."""
    expected = {
        "skills/build/SKILL.md": ["superpowers:test-driven-development",
                                  "superpowers:systematic-debugging",
                                  "superpowers:verification-before-completion",
                                  "superpowers:receiving-code-review"],
        "agents/builder.md": ["superpowers:test-driven-development",
                              "superpowers:systematic-debugging",
                              "superpowers:verification-before-completion"],
        "skills/architect/stage-brainstorm.md": ["superpowers:brainstorming"],
        "skills/review/SKILL.md": ["superpowers:requesting-code-review"],
        "agents/reviewer.md": ["superpowers:requesting-code-review"],
    }
    missing = []
    for rel, names in expected.items():
        body = (PLUGIN_ROOT / rel).read_text()
        missing += [f"{rel}: {n}" for n in names if n not in body]
    assert not missing, f"inner-loop hand-offs not wired: {missing}"


def test_the_three_attempts_debugging_rule_is_gone():
    """It told the agent to retry blind twice before thinking; D-014 replaces
    it with systematic-debugging on the FIRST red."""
    offenders = []
    for rel in ("skills/build/SKILL.md", "agents/builder.md",
                "templates/claude-builder.sh",
                "templates/claude-builder-sdk.py"):
        body = (PLUGIN_ROOT / rel).read_text()
        if "superpowers:systematic-debugging" not in body:
            offenders.append(f"{rel}: no systematic-debugging hand-off")
    assert not offenders, offenders
