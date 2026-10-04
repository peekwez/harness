"""W4 upgrade steps (spec 12 step 13): create docs/glossary.md and add the
STE-80 rule to a harness-marked AGENTS.md.

Each step is a describe/apply pair registered at import; add later W4 steps
as further `register(Step(...))` calls in this module.
"""
from __future__ import annotations

import re
from pathlib import Path

from .lint_text import GLOSSARY_PATH, scaffold_glossary
from .upgrade_010 import Ask, Step, register


def _describe(root: Path) -> list[str]:
    root = Path(root)
    if (root / GLOSSARY_PATH).exists() or (root / "docs").is_file():
        return []
    return [f"create {GLOSSARY_PATH} from the glossary template"]


def _apply(root: Path, ask: Ask) -> list[str]:
    if not _describe(root):
        return []
    scaffold_glossary(root)
    return [f"created {GLOSSARY_PATH}"]


def _advise(root: Path) -> list[str]:
    if (Path(root) / "docs").is_file():
        return ["check: docs is a file, so harness cannot create "
                f"{GLOSSARY_PATH}. Move it, then rerun upgrade."]
    return []


GLOSSARY_STEP = register(Step(
    id="w4.glossary",
    title="Create docs/glossary.md when it does not exist.",
    describe=_describe,
    apply=_apply,
    advise=_advise,
))


AGENTS_MARKER = "<!-- harness:agents-md 0.10 -->"
STE80_RULE = (
    "6. STE-80: write for humans in short, active sentences with one action "
    "per step. Use one name per concept from `docs/glossary.md`. Rules: "
    "skill `harness:harness`, file `ste80.md`. Check: "
    "`harness lint-text <paths>`.")
_NUMBERED = re.compile(r"^(\d+)\. ")
_HAS_RULE = re.compile(r"^\d+\. STE-80:", re.MULTILINE)


def _agents_text(root: Path) -> str | None:
    path = Path(root) / "AGENTS.md"
    try:
        with open(path, newline="") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return None


def _section(lines: list[str]) -> tuple[int, int] | None:
    """The line range after `## Binding rules`, up to the next heading."""
    try:
        start = lines.index("## Binding rules") + 1
    except ValueError:
        return None
    end = next((i for i in range(start, len(lines))
                if lines[i].startswith("## ")), len(lines))
    return start, end


def _has_rule(text: str) -> bool:
    lines = text.splitlines()
    span = _section(lines)
    return bool(span) and any(_HAS_RULE.match(line)
                              for line in lines[span[0]:span[1]])


def _insertion(text: str) -> tuple[list[str], int, str] | None:
    """The lines, the index after the last binding rule, and its new rule."""
    lines = text.splitlines()
    span = _section(lines)
    if span is None:
        return None
    start, end = span
    numbers = [(i, int(m.group(1))) for i in range(start, end)
               if (m := _NUMBERED.match(lines[i]))]
    if not numbers:
        return None
    at = numbers[-1][0] + 1
    while at < end and lines[at].strip() and not _NUMBERED.match(lines[at]):
        at += 1
    number = max(n for _, n in numbers) + 1
    return lines, at, STE80_RULE.replace("6.", f"{number}.", 1)


def _agents_describe(root: Path) -> list[str]:
    text = _agents_text(root)
    if (text is None or AGENTS_MARKER not in text or _has_rule(text)
            or _insertion(text) is None):
        return []
    return ["add the STE-80 rule to AGENTS.md binding rules"]


def _agents_apply(root: Path, ask: Ask) -> list[str]:
    if not _agents_describe(root):
        return []
    text = _agents_text(root)
    lines, at, rule = _insertion(text)
    lines.insert(at, rule)
    eol = "\r\n" if "\r\n" in text else "\n"
    tail = eol if text.endswith("\n") else ""
    with open(Path(root) / "AGENTS.md", "w", newline="") as handle:
        handle.write(eol.join(lines) + tail)
    return ["added the STE-80 rule to AGENTS.md"]


def _agents_advise(root: Path) -> list[str]:
    text = _agents_text(root)
    if text is None:
        return []
    if AGENTS_MARKER not in text:
        return ["check: AGENTS.md has no harness 0.10 marker, so upgrade "
                "leaves it alone. Add the STE-80 rule from "
                "templates/agents-md.md by hand."]
    if _has_rule(text):
        return []
    if _insertion(text) is None:
        return ["check: AGENTS.md has no numbered list under Binding rules. "
                "Add the STE-80 rule from templates/agents-md.md by hand."]
    return []


AGENTS_STE80_STEP = register(Step(
    id="w4.agents-md-ste80",
    title="Add the STE-80 rule to a harness-marked AGENTS.md.",
    describe=_agents_describe,
    apply=_agents_apply,
    advise=_agents_advise,
))
