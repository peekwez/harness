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
