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
    "per step. Rules: skill `harness:harness`, file `ste80.md`. Check: "
    "`harness lint-text <paths>`.")
_NUMBERED = re.compile(r"^(\d+)\. ")


def _agents_text(root: Path) -> str | None:
    path = Path(root) / "AGENTS.md"
    try:
        return path.read_text()
    except (OSError, UnicodeDecodeError):
        return None


def _insertion(text: str) -> tuple[list[str], int, str] | None:
    """The lines, the index after the last binding rule, and its new rule."""
    lines = text.splitlines()
    try:
        start = lines.index("## Binding rules")
    except ValueError:
        return None
    last = None
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            break
        if _NUMBERED.match(lines[i]):
            last = i
    if last is None:
        return None
    number = int(_NUMBERED.match(lines[last]).group(1)) + 1
    return lines, last + 1, STE80_RULE.replace("6.", f"{number}.", 1)


def _agents_describe(root: Path) -> list[str]:
    text = _agents_text(root)
    if (text is None or AGENTS_MARKER not in text or "STE-80" in text
            or _insertion(text) is None):
        return []
    return ["add the STE-80 rule to AGENTS.md binding rules"]


def _agents_apply(root: Path, ask: Ask) -> list[str]:
    if not _agents_describe(root):
        return []
    text = _agents_text(root)
    lines, at, rule = _insertion(text)
    lines.insert(at, rule)
    tail = "\n" if text.endswith("\n") else ""
    (Path(root) / "AGENTS.md").write_text("\n".join(lines) + tail)
    return ["added the STE-80 rule to AGENTS.md"]


def _agents_advise(root: Path) -> list[str]:
    text = _agents_text(root)
    if text is None or "STE-80" in text:
        return []
    if AGENTS_MARKER not in text:
        return ["check: AGENTS.md has no harness 0.10 marker, so upgrade "
                "leaves it alone. Add the STE-80 rule from "
                "templates/agents-md.md by hand."]
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
