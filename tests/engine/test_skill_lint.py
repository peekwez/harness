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


AGENT_GUIDANCE = ("skills/close-slice/SKILL.md", "skills/shadow-context/SKILL.md",
                  "agents/builder.md", "adapters/opencode/harness.js",
                  "adapters/opencode/README.md")
STALE_010 = re.compile(
    r"\bG[247]\b|G4[-–]G8|\.harness/shadows|shadows_extracted|shadow regen")


def test_agent_guidance_names_no_removed_gate_or_committed_shadow():
    """0.10 removed G2, G4 and G7, and shadows became a gitignored cache.
    Guidance an agent reads must not send it after either."""
    offenders = [
        f"{rel}:{i}: {line.strip()}"
        for rel in AGENT_GUIDANCE
        for i, line in enumerate((PLUGIN_ROOT / rel).read_text().splitlines(), 1)
        if STALE_010.search(line)]
    assert not offenders, "\n".join(offenders)
