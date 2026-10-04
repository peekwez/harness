"""Explore: a quick toy, decision cards and verify statements (spec 5).

`harness explore` creates `explore/` and three files from templates.
`harness explore --freeze` checks the cards and the statements, then
signs `explore/DECISIONS.md` with `frozen_by` and `frozen_at_commit`.
`harness architect --from-explore` (engine/explore_adr.py) reads the
frozen cards. `--skip-explore "<reason>"` writes a marker into the working
document; close reads it into slice metrics.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from engine import HarnessError

EXPLORE_DIR = "explore"
FILES = ("DECISIONS.md", "VERIFY.md", "OPEN.md")
TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "explore"

CARD_FIELDS = ("Why now", "Evidence", "Would change it", "Chosen", "Reason")
OPTIONAL_CARD_FIELDS = ("Domain",)
OPTION_FIELDS = ("Solves", "Example", "Trade-off", "1st order",
                 "2nd order", "3rd order", "Undo cost")
MAX_SENTENCES = 2

_FRONT = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.S)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_CARD = re.compile(r"^##\s+(D-[A-Za-z0-9-]+)\s*:\s*(.+?)\s*$")
_OTHER_H2 = re.compile(r"^#{1,2}\s")
_OPTION = re.compile(r"^###\s+Option\s+([A-Z])\s*:\s*(.+?)\s*$")
_RECOMMENDED = re.compile(r"\s*\(recommended\)\s*$", re.I)
_CARD_FIELD = re.compile(r"^\*\*([^*:]+):\*\*\s*(.*)$")
_OPTION_FIELD = re.compile(r"^[-*]\s+([^:]+?):\s*(.*)$")
_SENTENCE_END = re.compile(r"[.!?](?=\s+[A-Z0-9\"'(`])")
_UNDO = re.compile(r"^(low|medium|high)\b\s*[,:;.-]?\s*\S", re.I)
_NO_EVIDENCE = re.compile(r"^no evidence\b", re.I)
_NO_EVIDENCE_OK = re.compile(r"^no evidence:\s*\S", re.I)
_CHOSEN = re.compile(r"^(?:option\s+)?([A-Z])\b|^(parked)\b", re.I)
_STATEMENT_LINE = re.compile(
    r"^\s*(?:[-*]\s+)?(?:\*\*)?`?(V-[^\s:`*]*)`?(?:\*\*)?\s*:\s*(.*)$")
_OPEN_HEAD = re.compile(r"^##\s+(\S+?)\s*:\s*(.+?)\s*$")
_OPEN_FIELD = re.compile(r"^[-*]\s+(Owner|Trigger)\s*:\s*(.*)$", re.I)
SKIP_MARKER = re.compile(r"^<!-- explore-skipped: (.*?) -->[ \t]*$", re.M)
_OPTION_KEYS = {f.lower(): f for f in OPTION_FIELDS}
_CARD_KEYS = {f.lower(): f for f in CARD_FIELDS + OPTIONAL_CARD_FIELDS}


# ------------------------------------------------------------------ scaffold
def explore_path(root, name: str = "") -> Path:
    """`<root>/explore`, or a file in it when `name` is given."""
    folder = Path(root) / EXPLORE_DIR
    return folder / name if name else folder


def explore_active(root) -> bool:
    """True when `harness explore` made this repo's `explore/` folder."""
    return explore_path(root, "DECISIONS.md").is_file()


def scaffold(root) -> dict:
    """Creates `explore/` and the three files. Never overwrites a file.

    Args:
        root: Repo root.

    Returns:
        `{"dir", "created", "kept", "next"}`, plus `warning` when the
        folder already held other files before `DECISIONS.md` existed.

    Raises:
        HarnessError: A template file is missing from the install.
    """
    folder = explore_path(root)
    foreign = (folder.is_dir()
               and not (folder / "DECISIONS.md").exists()
               and any(p.name not in FILES for p in folder.iterdir()))
    folder.mkdir(parents=True, exist_ok=True)
    created, kept = [], []
    for name in FILES:
        target = folder / name
        rel = f"{EXPLORE_DIR}/{name}"
        if target.exists():
            kept.append(rel)
            continue
        source = TEMPLATES / name
        if not source.is_file():
            raise HarnessError(f"explore: template {source} is missing. "
                               f"Reinstall harness.")
        target.write_text(source.read_text(encoding="utf-8"),
                          encoding="utf-8")
        created.append(rel)
    result = {"dir": f"{EXPLORE_DIR}/", "created": created, "kept": kept,
              "next": "Build the toy in explore/. Write cards in "
                      "explore/DECISIONS.md. Then run: harness explore "
                      "--freeze"}
    if foreign:
        result["warning"] = ("explore/ already held other files. G9 now "
                             "blocks production imports from them. Move "
                             "production code out of explore/.")
    return result
