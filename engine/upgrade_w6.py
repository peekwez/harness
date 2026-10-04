"""W6 upgrade step: add `explore` to the AGENTS.md workflow line.

Registered at import; add later W6 steps as further `register(Step(...))`
calls in this module.
"""
from __future__ import annotations

import re
from pathlib import Path

from .upgrade_010 import Ask, Step, register
from .upgrade_w4 import AGENTS_MARKER, _agents_text

WORKFLOW_NEW = ("init -> explore -> architect -> author-gate "
                "# Phase 0: a human signs")
_OLD = re.compile(r"^init -> architect -> author-gate( +)# Phase 0",
                  re.MULTILINE)
_WORKFLOW = re.compile(r"^.*\barchitect\s*->.*$", re.MULTILINE)


def _describe(root: Path) -> list[str]:
    text = _agents_text(root)
    if text is None or AGENTS_MARKER not in text or not _OLD.search(text):
        return []
    return ["add explore to the AGENTS.md workflow line"]


def _apply(root: Path, ask: Ask) -> list[str]:
    if not _describe(root):
        return []
    text = _agents_text(root)
    new = _OLD.sub("init -> explore -> architect -> author-gate # Phase 0",
                   text, count=1)
    with open(Path(root) / "AGENTS.md", "w", newline="") as handle:
        handle.write(new)
    return ["added explore to the AGENTS.md workflow line"]


def _advise(root: Path) -> list[str]:
    text = _agents_text(root)
    if text is None:
        return []
    if AGENTS_MARKER in text:
        line = _WORKFLOW.search(text)
        if line is None or "explore" in line.group(0) or _OLD.search(text):
            return []
        return ["check: add explore before architect in the AGENTS.md "
                "workflow line by hand."]
    from .upgrade_w2 import AGENTS_MARKERS
    if text.splitlines()[:1] == [AGENTS_MARKERS[0]]:
        return []  # 0.9 file: w8.agents-md swaps in the 0.10 template
    return ["check: AGENTS.md has no harness 0.10 marker, so upgrade leaves "
            "it alone. Add explore to the workflow line by hand."]


AGENTS_EXPLORE_STEP = register(Step(
    id="w6.agents-md-explore",
    title="Add explore to the AGENTS.md workflow line.",
    describe=_describe,
    apply=_apply,
    advise=_advise,
))
