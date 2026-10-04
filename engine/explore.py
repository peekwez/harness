"""Explore: a quick toy, decision cards and verify statements (spec 5).

`harness explore` creates `explore/` and three files from templates.
`harness explore --freeze` checks the cards and the statements, then
signs `explore/DECISIONS.md` with `frozen_by` and `frozen_at_commit`.
`harness architect --from-explore` (engine/explore_adr.py) reads the
frozen cards. `--skip-explore "<reason>"` writes a marker into the working
document; close reads it into slice metrics.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

from engine import HarnessError
from engine.findings import clip_words

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
_CARD_LOOSE = re.compile(r"^##\s+(D-[A-Za-z0-9-]*)")
_OPTION_LOOSE = re.compile(r"^###\s+Option\b", re.I)
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_FENCE_CLOSE = re.compile(r"^\s*(`{3,}|~{3,})\s*$")
_OTHER_H2 = re.compile(r"^#{1,2}\s")
_OPTION = re.compile(r"^###\s+Option\s+([A-Z])\s*:\s*(.+?)\s*$")
_RECOMMENDED = re.compile(r"\s*\(recommended\)\s*$", re.I)
_CARD_FIELD = re.compile(r"^\*\*([^*:]+):\*\*\s*(.*)$")
_OPTION_FIELD = re.compile(r"^[-*]\s+([^:]+?):\s*(.*)$")
_SENTENCE_END = re.compile(r"[.!?](?=\s+[A-Z0-9\"'(`])")
_UNDO = re.compile(r"^(low|medium|high)\b\s*[,:;.-]?\s*\S", re.I)
_UNDO_TEMPLATE = re.compile(r"^low\s*\|\s*medium\s*\|\s*high\b", re.I)
# a template slot such as `<why>`: at the start, or after a space, `(` or
# `:`, so code like `Vec<u8>` is not template text
_SLOT = re.compile(r"(?:^|(?<=[\s(:]))<[a-z][^<>\n]*>")
_NO_EVIDENCE = re.compile(r"^no evidence\b", re.I)
_NO_EVIDENCE_OK = re.compile(r"^no evidence:\s*\S", re.I)
_CHOSEN = re.compile(r"(?:option\s+)?([A-Z])|(parked)", re.I)
_CARD_ID = re.compile(r"D-E[0-9]+")
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
    warnings = []
    for name in FILES:
        target = folder / name
        rel = f"{EXPLORE_DIR}/{name}"
        if target.is_symlink() and not target.exists():
            warnings.append(f"{rel} is a broken symlink, so harness did not "
                            f"write it. Remove the link, then run harness "
                            f"explore again.")
            continue
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
        warnings.insert(0, "explore/ already held other files. G9 now "
                           "blocks production imports from them. Move "
                           "production code out of explore/.")
    if warnings:
        result["warning"] = " ".join(warnings)
    return result


# ------------------------------------------------------------------ text helpers
def _blank(match) -> str:
    """Replaces a match with its newlines, so line numbers stay true."""
    return "\n" * match.group(0).count("\n")


def front_matter(text: str) -> tuple[dict, str]:
    """Splits YAML front matter from a markdown file.

    Args:
        text: The whole file.

    Returns:
        (front matter mapping, body). A file with no front matter gives
        ({}, text).

    Raises:
        HarnessError: The front matter is not a YAML mapping.
    """
    m = _FRONT.match(text)
    if not m:
        return {}, text
    import yaml
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise HarnessError(f"front matter is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise HarnessError("front matter must be a YAML mapping")
    return data, text[m.end():]


def set_front_matter(text: str, updates: dict) -> str:
    """Returns `text` with `updates` merged into its front matter."""
    import yaml
    data, body = front_matter(text)
    data.update(updates)
    head = yaml.safe_dump(data, sort_keys=False, allow_unicode=True,
                          width=1000).rstrip("\n")
    return f"---\n{head}\n---\n{body}"


def _clean_fences(text: str) -> tuple[str, int | None]:
    """Blanks fenced code. Returns (text, line of an unclosed fence or None).

    A closing fence has the opener's character, at least as many of them,
    and no info string. Text after an unclosed fence stays visible.
    """
    out: list[str] = []
    held: list[str] = []
    fence = None  # (character, length, line number)
    for n, line in enumerate(text.split("\n"), 1):
        if fence is None:
            m = _FENCE.match(line)
            if m:
                fence = (m.group(1)[0], len(m.group(1)), n)
                held = [line]
            else:
                out.append(line)
            continue
        held.append(line)
        m = _FENCE_CLOSE.match(line)
        if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1]:
            out.extend([""] * len(held))
            fence, held = None, []
    if fence is not None:
        out.extend(held)
        return "\n".join(out), fence[2]
    return "\n".join(out), None


def _clean(text: str) -> str:
    """Front matter, HTML comments and fenced code become blank lines."""
    text = _FRONT.sub(_blank, text, count=1)
    text = _COMMENT.sub(_blank, text)
    return _clean_fences(text)[0]


class CardList(list):
    """The cards of a file. `unclosed_fence` is a line number or None."""
    unclosed_fence: int | None = None


def sentence_count(text: str) -> int:
    """Counts sentences: an end mark followed by a space and a capital."""
    text = text.strip()
    return 0 if not text else len(_SENTENCE_END.findall(text)) + 1


def _placeholder(value: str) -> bool:
    """True when `value` still holds template text: a `<slot>`, or the
    template's `low | medium | high` undo levels."""
    value = value.strip()
    if value.startswith("<") and value.endswith(">"):
        return True
    return bool(_SLOT.search(value) or _UNDO_TEMPLATE.match(value))


# ------------------------------------------------------------------ cards
def parse_cards(text: str) -> list[dict]:
    """Reads decision cards from `explore/DECISIONS.md`.

    Args:
        text: The file content. Front matter and HTML comments are ignored.

    Returns:
        One dict per `## D-<id>: <question>` heading:
        `{"id", "question", "line", "raw", "fields", "options", "unknown"}`.
        `fields` maps card field names to values. `options` holds
        `{"letter", "name", "recommended", "fields"}`. `unknown` lists
        field labels that are not in the card format.
    """
    cleaned, unclosed = _clean_fences(
        _COMMENT.sub(_blank, _FRONT.sub(_blank, text, count=1)))
    lines = cleaned.splitlines()
    raw_lines = text.splitlines()
    cards = CardList()
    cards.unclosed_fence = unclosed
    card = option = None
    last = None  # (mapping, key) that a continuation line extends
    for i, line in enumerate(lines):
        stripped = line.strip()
        head = _CARD.match(line)
        loose = None if head else _CARD_LOOSE.match(line)
        if head or loose:
            if card is not None:
                card["end"] = i
            card = {"id": (head or loose).group(1),
                    "question": head.group(2) if head else "",
                    "line": i + 1, "start": i, "end": len(lines),
                    "bad_heading": head is None, "bad_options": [],
                    "repeated": [], "fields": {}, "options": [],
                    "unknown": []}
            cards.append(card)
            option, last = None, None
            continue
        if card is None:
            continue
        if _OTHER_H2.match(line):
            card["end"] = i
            card = option = last = None
            continue
        opt = _OPTION.match(line)
        if not opt and _OPTION_LOOSE.match(line):
            card["bad_options"].append(stripped)
            option = last = None
            continue
        if opt:
            name = opt.group(2)
            option = {"letter": opt.group(1),
                      "name": _RECOMMENDED.sub("", name).strip(),
                      "recommended": bool(_RECOMMENDED.search(name)),
                      "fields": {}, "repeated": []}
            card["options"].append(option)
            last = None
            continue
        field = _CARD_FIELD.match(stripped)
        if field:
            key = _CARD_KEYS.get(field.group(1).strip().lower())
            option = None
            if key is None:
                card["unknown"].append(field.group(1).strip())
                last = None
            else:
                if key in card["fields"]:
                    card["repeated"].append(key)
                card["fields"][key] = field.group(2).strip()
                last = (card["fields"], key)
            continue
        ofield = _OPTION_FIELD.match(stripped)
        if ofield and option is not None:
            key = _OPTION_KEYS.get(ofield.group(1).strip().lower())
            if key is None:
                card["unknown"].append(ofield.group(1).strip())
                last = None
            else:
                if key in option["fields"]:
                    option["repeated"].append(key)
                option["fields"][key] = ofield.group(2).strip()
                last = (option["fields"], key)
            continue
        if not stripped:
            last = None
            continue
        if last is not None:
            mapping, key = last
            mapping[key] = (mapping[key] + " " + stripped).strip()
    for c in cards:
        c["raw"] = "\n".join(raw_lines[c.pop("start"):c.pop("end")]).strip()
    return cards


def chosen_letter(card: dict) -> str | None:
    """`"A"`, `"parked"` or None when `Chosen` is not a valid answer."""
    m = _CHOSEN.fullmatch(card["fields"].get("Chosen", "").strip())
    if not m:
        return None
    return "parked" if m.group(2) else m.group(1).upper()


def chosen_option(card: dict) -> dict | None:
    """The option dict that `Chosen` names, or None (parked or invalid)."""
    letter = chosen_letter(card)
    return next((o for o in card["options"] if o["letter"] == letter), None)


def _field_problems(where: str, name: str, value: str | None) -> list[str]:
    if value is None or not value.strip():
        return [f"{where}: field '{name}' is missing or empty. Write it."]
    if _placeholder(value):
        return [f"{where}: field '{name}' still has template text. "
                f"Replace it."]
    if sentence_count(value) > MAX_SENTENCES:
        return [f"{where}: field '{name}' has more than {MAX_SENTENCES} "
                f"sentences. Shorten it."]
    return []


def validate_cards(cards: list[dict]) -> list[str]:
    """Checks each card against the card format (spec 5.2).

    Args:
        cards: The output of `parse_cards`.

    Returns:
        One STE-80 problem line per defect. An empty list means valid.
    """
    problems: list[str] = []
    line = getattr(cards, "unclosed_fence", None)
    if line:
        problems.append(f"Line {line}: a code fence opens here and never "
                        f"closes. Close it with ```.")
    if not cards:
        return problems + ["explore/DECISIONS.md has no decision cards. "
                           "Write one card for each big decision."]
    seen: set[str] = set()
    for card in cards:
        cid = card["id"]
        if cid in seen:
            problems.append(f"{cid}: the card id is used twice. Give each "
                            f"card its own id.")
        seen.add(cid)
        if not _CARD_ID.fullmatch(cid):
            problems.append(f"{cid}: the card id must look like "
                            f"D-E<number>. Rename it, for example D-E1.")
        if card["bad_heading"]:
            problems.append(f"{cid} line {card['line']}: the heading must "
                            f"look like '## D-E1: <question>'. Fix the "
                            f"heading.")
        for bad in card["bad_options"]:
            problems.append(f"{cid}: option heading {clip_words(bad, 5)!r} "
                            f"must look like '### Option A: <name>'. Fix "
                            f"the heading.")
        for name in card["repeated"]:
            problems.append(f"{cid}: field '{name}' appears twice. Remove "
                            f"one.")
        for label in card["unknown"]:
            label = clip_words(label, 5)
            problems.append(f"{cid}: '{label}' is not a card field. Use the "
                            f"field names in the card format.")
        for name in CARD_FIELDS:
            problems += _field_problems(cid, name, card["fields"].get(name))
        evidence = card["fields"].get("Evidence", "")
        if _NO_EVIDENCE.match(evidence) and not _NO_EVIDENCE_OK.match(evidence):
            problems.append(f"{cid}: 'no evidence' needs a reason. Write "
                            f"'no evidence: <reason>'.")
        options = card["options"]
        if len(options) < 2:
            problems.append(f"{cid}: a card needs two or more options. Add "
                            f"the option you did not recommend.")
        letters = [o["letter"] for o in options]
        for letter in sorted({x for x in letters if letters.count(x) > 1}):
            problems.append(f"{cid}: option {letter} is used twice. Give "
                            f"each option its own letter.")
        if sum(o["recommended"] for o in options) != 1:
            problems.append(f"{cid}: exactly one option must be recommended. "
                            f"Mark one option '(recommended)'.")
        for o in options:
            where = f"{cid} option {o['letter']}"
            for name in o["repeated"]:
                problems.append(f"{where}: field '{name}' appears twice. "
                                f"Remove one.")
            for name in OPTION_FIELDS:
                problems += _field_problems(where, name, o["fields"].get(name))
            undo = o["fields"].get("Undo cost", "")
            if undo and not _placeholder(undo) and not _UNDO.match(undo):
                problems.append(f"{where}: 'Undo cost' must start with low, "
                                f"medium or high, then say why.")
        chosen = card["fields"].get("Chosen", "")
        letter = chosen_letter(card)
        if chosen and not _placeholder(chosen) and (
                letter is None
                or (letter != "parked" and letter not in letters)):
            shown = clip_words(chosen, 5)
            problems.append(f"{cid}: 'Chosen' is {shown!r}. Write an "
                            f"option letter from this card, or 'parked'.")
    return problems


# ------------------------------------------------------------------ OPEN.md / VERIFY.md
def parse_open(text: str) -> dict[str, dict]:
    """Reads parked questions: `## <id>: <question>` plus Owner and Trigger.

    Returns:
        Map from question id to `{"question", "owner", "trigger"}`.
    """
    out: dict[str, dict] = {}
    current = None
    for line in _clean(text).splitlines():
        head = _OPEN_HEAD.match(line)
        if head:
            current = {"question": head.group(2), "owner": "", "trigger": ""}
            out[head.group(1)] = current
            continue
        field = _OPEN_FIELD.match(line.strip())
        if field and current is not None:
            current[field.group(1).lower()] = field.group(2).strip()
    return out


def check_statements(text: str) -> tuple[list[dict], list[str]]:
    """Checks `explore/VERIFY.md` the way `harness compile` reads it.

    Args:
        text: The file content. Fenced blocks are skipped. HTML comments
            are not: compile reads them (spec 6.1).

    Returns:
        (statements from `engine.statements.parse_statements`, problems).
    """
    from engine.statements import parse_statements, skipped_statement_lines
    source = f"{EXPLORE_DIR}/VERIFY.md"
    problems: list[str] = []
    try:
        statements = parse_statements(text, source)
    except HarnessError as exc:
        problems.append(str(exc))
        statements = []
    problems += skipped_statement_lines(text, source)
    if not statements and not problems:
        problems.append("explore/VERIFY.md has no statements. Write one "
                        "V-<feature>-<n> line for each feature.")
    return statements, problems


# ------------------------------------------------------------------ git
def _git(root, *args) -> str:
    proc = subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def git_identity(root) -> str:
    """`Name <email>` from git config, or "" when user.name is not set."""
    name = _git(root, "config", "user.name")
    email = _git(root, "config", "user.email")
    if not name:
        return ""
    return f"{name} <{email}>" if email else name


# ------------------------------------------------------------------ freeze
def body_digest(text: str) -> str:
    """sha256 of the DECISIONS.md body, without front matter."""
    return hashlib.sha256(front_matter(text)[1].encode("utf-8")).hexdigest()


def freeze_state(root) -> dict | None:
    """`{"frozen_by", "frozen_at_commit"}` from DECISIONS.md, or None.

    The digest is read with `body_digest`; compare it to `frozen_digest`.
    """
    path = explore_path(root, "DECISIONS.md")
    if not path.is_file():
        return None
    try:
        data, _ = front_matter(path.read_text(encoding="utf-8"))
    except HarnessError:
        return None
    who, commit = data.get("frozen_by"), data.get("frozen_at_commit")
    if not who or not commit:
        return None
    return {"frozen_by": str(who), "frozen_at_commit": str(commit)}


def _row_problems(cards: list[dict]) -> list[str]:
    """The `architect --from-explore` row limit, checked at freeze time."""
    from engine.explore_adr import row_answer
    problems = []
    for card in cards:
        if chosen_letter(card) == "parked":
            continue
        try:
            row_answer(card, "adr/000-decision.md")
        except HarnessError as exc:
            problems.append(str(exc))
    return problems


def freeze(root) -> dict:
    """Checks explore/ and signs DECISIONS.md (spec 5.5).

    Args:
        root: Repo root.

    Returns:
        `{"frozen": bool, "problems": [...]}` plus, when frozen,
        `frozen_by`, `frozen_at_commit`, `frozen_digest`, `cards`, `chosen`, `parked` and
        `statements`. Nothing is written when `problems` is not empty.
    """
    root = Path(root)
    missing = [f"explore/{n} is missing. Run: harness explore"
               for n in FILES if not explore_path(root, n).is_file()]
    if missing:
        return {"frozen": False, "problems": missing}
    decisions_path = explore_path(root, "DECISIONS.md")
    text = decisions_path.read_text(encoding="utf-8")
    problems: list[str] = []
    try:
        front_matter(text)
    except HarnessError as exc:
        problems.append(f"explore/DECISIONS.md: {exc}. Fix the front matter.")
    cards = parse_cards(text)
    problems += validate_cards(cards)
    opens = parse_open(explore_path(root, "OPEN.md")
                       .read_text(encoding="utf-8"))
    parked = [c for c in cards if chosen_letter(c) == "parked"]
    for card in parked:
        entry = opens.get(card["id"])
        if entry is None or not entry["owner"] or not entry["trigger"] \
                or _placeholder(entry["owner"]) \
                or _placeholder(entry["trigger"]):
            problems.append(f"{card['id']} is parked but explore/OPEN.md has "
                            f"no owner and trigger for it. Add them.")
    if not problems:
        problems += _row_problems(cards)
    statements, statement_problems = check_statements(
        explore_path(root, "VERIFY.md").read_text(encoding="utf-8"))
    problems += statement_problems
    who = git_identity(root)
    if not who:
        problems.append("git user.name is not set. Run: git config "
                        "user.name \"<your name>\"")
    commit = _git(root, "rev-parse", "HEAD")
    if not commit:
        problems.append("the repo has no commit. Commit explore/, then "
                        "freeze again.")
    if problems:
        return {"frozen": False, "problems": problems}
    digest = body_digest(text)
    decisions_path.write_text(
        set_front_matter(text, {"frozen_by": who, "frozen_at_commit": commit,
                                "frozen_digest": digest}),
        encoding="utf-8")
    return {"frozen": True, "problems": [], "frozen_by": who,
            "frozen_at_commit": commit, "frozen_digest": digest,
            "cards": len(cards),
            "chosen": len(cards) - len(parked), "parked": len(parked),
            "statements": len(statements)}


# ------------------------------------------------------------------ skip-explore
def _one_line(reason: str) -> str:
    return " ".join((reason or "").split()).replace("-->", "->")


def record_skip(doc_text: str | None, reason: str) -> str:
    """Writes the `--skip-explore` reason into a working document.

    Args:
        doc_text: The current document, or None for a new one.
        reason: The human's reason. Whitespace collapses to one line.

    Returns:
        The new document text. A new document starts at stage 1. An
        existing document keeps its content and gets one marker line.

    Raises:
        HarnessError: The reason is empty.
    """
    from engine.docsections import DECISIONS_TABLE_HEADER
    reason = _one_line(reason)
    if not reason:
        raise HarnessError("architect: --skip-explore needs a reason. Run: "
                           "harness architect --skip-explore \"<why no toy>\"")
    marker = f"<!-- explore-skipped: {reason} -->"
    if doc_text is None:
        return "\n".join([
            "# Architecture", "", "<!-- stage: 1 -->", marker, "",
            f"[assumption] Explore was skipped: {reason}", "",
            "```harness-decisions", *DECISIONS_TABLE_HEADER, "```", ""])
    lines = doc_text.split("\n")
    cleaned, _ = _clean_fences(doc_text)
    for n, line in enumerate(cleaned.split("\n")):
        if SKIP_MARKER.match(line):
            lines[n] = marker
            return "\n".join(lines)
    fm = _FRONT.match(doc_text)
    at = doc_text[:fm.end()].count("\n") if fm else 0
    if fm:
        lines[at:at] = [marker, ""]
    elif lines and lines[0].startswith("#"):
        lines[1:1] = ["", marker]
    else:
        lines[0:0] = [marker]
    return "\n".join(lines)


def skip_reason(root) -> str | None:
    """The recorded `--skip-explore` reason, read from the working document.

    `docs/architecture.md` is read first. Other `docs/**/*.md` files are
    read in path order, because `architect --doc` can name another file.
    Markers inside fenced code blocks do not count.
    """
    found = _skip_marker(root)
    return found[0] if found else None


_EXPLORE_BLOCK = re.compile(r"^\[constraint\]\s+D-E[0-9]+\s*:", re.M)


def _skip_marker(root) -> tuple[str, str] | None:
    """(reason, fence-free document text) of the first skip marker."""
    docs = Path(root) / "docs"
    if not docs.is_dir():
        return None
    default = docs / "architecture.md"
    candidates = [default] + sorted(p for p in docs.rglob("*.md")
                                    if p != default)
    for path in candidates:
        if not path.is_file():
            continue
        text, _ = _clean_fences(path.read_text(encoding="utf-8",
                                               errors="replace"))
        m = SKIP_MARKER.search(text)
        if m:
            return m.group(1), text
    return None


def explore_summary_extra(root) -> dict:
    """Slice-metrics fields for `record_slice_summary(..., extra=)`.

    The skip marker counts unless the document holding it was seeded by
    `architect --from-explore`: it has a `[constraint] D-E<n>:` block. A
    frozen `explore/` from an earlier design does not hide a later skip.

    Returns:
        `{"explore_skipped": "<reason>"}` when the design skipped explore;
        otherwise `{}`.
    """
    found = _skip_marker(root)
    if not found or _EXPLORE_BLOCK.search(found[1]):
        return {}
    return {"explore_skipped": found[0]}
