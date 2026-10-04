"""Skill-file lint: preflight `!` executions run through the host's
permission checker BEFORE positional-argument substitution, so a `$1` (or
`$ARGUMENTS`) inside one fails with "Contains simple_expansion" on current
Claude Code — the ceremony dies before the model ever sees it. Argument-
bearing commands belong in the body as the model's own first action;
preflights must be argument-free."""
import re

from conftest import PLUGIN_ROOT

PREFLIGHT = re.compile(r"^!`(.+)`\s*$")


def _preflights():
    for path in sorted((PLUGIN_ROOT / "skills").glob("*/SKILL.md")):
        for i, line in enumerate(path.read_text().splitlines(), 1):
            m = PREFLIGHT.match(line.strip())
            if m:
                yield path, i, m.group(1)


def test_preflight_commands_never_use_positional_arguments():
    offenders = [
        f"{path.relative_to(PLUGIN_ROOT)}:{i}: {cmd}"
        for path, i, cmd in _preflights()
        if re.search(r"\$(?:\d|ARGUMENTS)", cmd)]
    assert not offenders, (
        "preflight `!` commands are permission-checked before $1/$ARGUMENTS "
        "substitution and are rejected as un-analyzable — move these into "
        "the skill body as the model's first command:\n" + "\n".join(offenders))


def test_preflights_still_exist_where_no_argument_is_needed():
    """The fix is moving argument-bearing commands into the body — not
    deleting preflights wholesale. Argument-free ones must survive."""
    assert any(True for _ in _preflights()), \
        "expected at least one argument-free preflight to remain"


AGENT_GUIDANCE = ("skills/close-slice/SKILL.md", "skills/build/SKILL.md",
                  "skills/harness/SKILL.md",
                  "agents/builder.md", "adapters/opencode/harness.js",
                  "adapters/opencode/README.md")
STALE_010 = re.compile(
    r"\bG[2478]\b|G4[-–]G8|\.harness/shadows|shadows_extracted|shadow regen")


def test_agent_guidance_names_no_removed_gate_or_committed_shadow():
    """0.10 removed G2, G4 and G7, and shadows became a gitignored cache.
    Guidance an agent reads must not send it after either."""
    offenders = [
        f"{rel}:{i}: {line.strip()}"
        for rel in AGENT_GUIDANCE
        for i, line in enumerate((PLUGIN_ROOT / rel).read_text().splitlines(), 1)
        if STALE_010.search(line)]
    assert not offenders, "\n".join(offenders)


SKILLS_0_10 = {"adr-authoring", "architect", "backlog", "build",
               "close-slice", "design-review", "explore", "harness", "init",
               "review", "verification"}

REMOVED_SKILLS = ("adjudicate", "contract-first", "decision-tables",
                  "premortem", "review-rubrics", "shadow-context",
                  "slice-decomposition", "status")
OLD_SKILL_NAME = re.compile(
    r"harness:(?:%s)(?![\w-])|\b(?:%s) skill\b" % (
        "|".join(REMOVED_SKILLS),
        "|".join(n for n in REMOVED_SKILLS if n != "status")))
TEXT_SUFFIXES = {".md", ".py", ".json", ".yml", ".yaml", ".sh", ".js",
                 ".toml"}


def test_skill_set_follows_the_0_10_merge_map():
    present = {p.parent.name
               for p in (PLUGIN_ROOT / "skills").glob("*/SKILL.md")}
    assert present == SKILLS_0_10


def test_absorbed_skills_live_on_as_reference_files():
    for rel in ("architect/premortem.md", "adr-authoring/decision-tables.md",
                "backlog/slice-decomposition.md", "review/rubrics.md",
                "review/adjudicate.md", "harness/status.md"):
        assert (PLUGIN_ROOT / "skills" / rel).is_file(), rel


def test_absorbing_descriptions_carry_the_old_triggers():
    expect = {"architect": ["premortem", "contract"],
              "adr-authoring": ["decision-table", "convention"],
              "backlog": ["break this down", "split"],
              "build": ["shadow"],
              "review": ["rubric", "adjudicat"],
              "harness": ["status"]}
    for skill, words in expect.items():
        front = (PLUGIN_ROOT / "skills" / skill / "SKILL.md").read_text() \
            .split("---")[1]
        desc = next(line for line in front.splitlines()
                    if line.startswith("description:")).lower()
        missing = [w for w in words if w not in desc]
        assert not missing, (skill, missing)


def test_no_text_names_a_removed_skill():
    offenders = []
    for sub in ("skills", "agents", "templates", "hooks", "adapters", "engine"):
        for path in sorted((PLUGIN_ROOT / sub).rglob("*")):
            if (not path.is_file() or path.suffix not in TEXT_SUFFIXES
                    or "__pycache__" in path.parts
                    or path.name == "upgrade_w2.py"):   # holds the rename map
                continue
            for i, line in enumerate(
                    path.read_text(errors="replace").splitlines(), 1):
                if OLD_SKILL_NAME.search(line):
                    offenders.append(
                        f"{path.relative_to(PLUGIN_ROOT)}:{i}: {line.strip()}")
    assert not offenders, "\n".join(offenders)


def test_architect_agent_uses_decision_cards():
    body = (PLUGIN_ROOT / "agents" / "architect.md").read_text()
    assert "refuses to solution" not in body
    assert "decision card" in body


def test_close_slice_names_every_blocking_unit_complete_source():
    """R6: close blocks on G1, G6, cited non-goals (G3) and gates.extra."""
    text = (PLUGIN_ROOT / "skills" / "close-slice" / "SKILL.md").read_text()
    para = text[text.index("The unit_complete gates pass"):]
    para = para[:para.index("Reconciliation passes")]
    for needle in ("G1", "G6", "gates.extra", "cites", "(G3)"):
        assert needle in para, needle


def test_skills_and_agents_pass_lint_text():
    """Spec 9.2: skills and agents are STE-80 text. Rewrite flagged lines
    by skills/harness/ste80.md. The harness repo's docs/glossary.md applies
    when that file exists; otherwise templates/glossary.md does."""
    from engine.lint_text import format_row, lint_paths

    glossary = PLUGIN_ROOT / "docs" / "glossary.md"
    if not glossary.exists():
        glossary = PLUGIN_ROOT / "templates" / "glossary.md"
    rows = lint_paths([PLUGIN_ROOT / "skills", PLUGIN_ROOT / "agents"],
                      glossary)
    assert not rows, "\n".join(format_row(r) for r in rows)
