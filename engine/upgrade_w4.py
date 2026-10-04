"""W4 upgrade steps (spec 12 step 13): create docs/glossary.md.

Each step is a describe/apply pair registered at import; add later W4 steps
as further `register(Step(...))` calls in this module.
"""
from __future__ import annotations

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
