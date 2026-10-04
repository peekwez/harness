"""STE-80 text lint (spec 9.3, D-0.10-08).

`harness lint-text <paths>` checks sentence length, banned words and
glossary synonyms. It prints `file:line: rule: text` and exits 1 on any
finding. It skips front matter, fenced code, tables, headings and HTML
comments. It does not detect passive voice or meaning.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

LIST_LIMIT = 25    # list items and numbered steps
PROSE_LIMIT = 35   # paragraphs
GLOSSARY_PATH = "docs/glossary.md"
_TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "glossary.md"

# Each entry is a word or phrase that has a plainer replacement
# (skills/harness/ste80.md lists the replacements).
BANNED = (
    "utilize", "utilizes", "utilized", "utilizing", "utilization",
    "utilise", "utilises", "utilised", "utilising", "utilisation",
    "leverage", "leverages", "leveraged", "leveraging",
    "simply", "robust", "robustly", "seamless", "seamlessly",
    "in order to", "facilitate", "facilitates", "facilitated",
    "prior to", "in the event that", "due to the fact that",
    "at this point in time", "make use of", "is able to", "a number of",
    "basically", "essentially", "obviously", "needless to say",
    "it should be noted that", "going forward", "best-in-class",
    "cutting-edge", "world-class", "synergy", "synergies",
)

# CommonMark: up to 3 spaces of indent, then 3+ backticks or tildes. A backtick
# fence's info string holds no backtick, so "```` ```x ````" is inline code.
_FENCE = re.compile(r"^ {0,3}(?P<fence>`{3,}(?=[^`]*$)|~{3,})")
_FENCE_CLOSE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})\s*$")
_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_INLINE_CODE = re.compile(r"`[^`]*`")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+")
_SENTENCE_END = re.compile(r"(?<=[.!?])[\"')\]*]*\s+")
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’_/.-]*")
_GLOSSARY_ROW = re.compile(
    r"^\s*(?:[-*]\s+)?\**(?P<term>[^—*]+?)\**\s+—\s+.*?"
    r"\(not:\s*(?P<syn>[^)]*)\)\s*$")


def _phrase(word: str) -> re.Pattern:
    """Whole-word, case-insensitive match: `story` never matches `history`."""
    return re.compile(r"(?<![A-Za-z0-9-])" + re.escape(word) +
                      r"(?![A-Za-z0-9-])", re.I)


_BANNED_RE = [(w, _phrase(w)) for w in BANNED]


def load_glossary(path: Path | None) -> dict[str, str]:
    """Map each `not:` synonym (lower case) to its glossary term.

    A missing file or a line without a `not:` list adds nothing.
    """
    if path is None or not Path(path).is_file():
        return {}
    out = {}
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    for line in text.splitlines():
        m = _GLOSSARY_ROW.match(line)
        if not m:
            continue
        term = m.group("term").strip()
        for syn in m.group("syn").split(","):
            syn = syn.strip()
            if syn:
                out[syn.lower()] = term
    return out


def scaffold_glossary(root: Path) -> bool:
    """Copy the glossary template to `docs/glossary.md` when it is absent.

    Returns True when it wrote the file. It never overwrites a glossary.
    """
    target = Path(root) / GLOSSARY_PATH
    if target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(_TEMPLATE, target)
    return True


def _units(lines: list[str]):
    """Split markdown lines into checkable units.

    Returns (units, open_fence_line). A unit is (line_no, kind, text), kind
    "item" or "prose". Wrapped lines join their unit.
    """
    units, unit = [], None
    start = 0
    if lines and lines[0].strip() == "---":
        for j in range(1, len(lines)):
            if lines[j].strip() == "---":
                start = j + 1
                break
    fence, fence_line, comment = None, None, False

    def close():
        nonlocal unit
        if unit:
            units.append((unit[0], unit[1], " ".join(unit[2])))
            unit = None

    for n in range(start, len(lines)):
        raw, line_no = lines[n], n + 1
        stripped = raw.strip()
        if fence:
            c = _FENCE_CLOSE.match(raw)
            if (c and c.group("fence")[0] == fence[0]
                    and len(c.group("fence")) >= len(fence)):
                fence, fence_line = None, None
            continue
        m = _FENCE.match(raw)
        if m:
            close()
            fence, fence_line = m.group("fence"), line_no
            continue
        if comment or stripped.startswith("<!--"):
            comment = "-->" not in stripped
            continue
        item = _ITEM.match(raw)
        if not stripped or stripped.startswith(("#", "|")) or item:
            close()
            if item:
                unit = [line_no, "item", [raw[item.end():].strip()]]
            continue
        if stripped.startswith(">"):
            close()
            unit = [line_no, "prose", [stripped.lstrip("> ")]]
            continue
        if unit is None:
            unit = [line_no, "prose", []]
        unit[2].append(stripped)
    close()
    return units, fence_line


def _clean(text: str) -> str:
    """Inline code and URLs count as one word; link text stays."""
    text = _INLINE_CODE.sub("CODE", text)
    text = _LINK.sub(r"\1", text)
    return _URL.sub("URL", text)


def find_synonyms(text: str, glossary: dict[str, str]) -> list[tuple[str, str]]:
    """(synonym, term) for each glossary synonym in `text`.

    Inline code is not checked: `story` in backticks is a name, not prose.
    """
    clean = _clean(text)
    return [(syn, term) for syn, term in sorted(glossary.items())
            if _phrase(syn).search(clean)]


def lint_text(text: str, path: str,
              glossary: dict[str, str] | None = None) -> list[dict]:
    """Lint one markdown document.

    Returns rows `{"path", "line", "rule", "text"}`. Rules:
    `sentence-length`, `banned-word`, `glossary-synonym`, `unclosed-fence`.
    """
    units, open_fence = _units(text.splitlines())
    out = []
    for line_no, kind, unit in units:
        clean = _clean(unit)
        limit = LIST_LIMIT if kind == "item" else PROSE_LIMIT
        for sentence in _SENTENCE_END.split(clean):
            words = len(_WORD.findall(sentence))
            if words > limit:
                out.append({"path": path, "line": line_no,
                            "rule": "sentence-length",
                            "text": f"{words} words, limit {limit}: "
                                    f"{sentence.strip()[:60]}"})
        for word, rx in _BANNED_RE:
            if rx.search(clean):
                out.append({"path": path, "line": line_no,
                            "rule": "banned-word",
                            "text": f"{word!r}: write a plain word"})
        for syn, term in find_synonyms(unit, glossary or {}):
            out.append({"path": path, "line": line_no,
                        "rule": "glossary-synonym",
                        "text": f"{syn!r}: use {term!r}"})
    if open_fence:
        out.append({"path": path, "line": open_fence,
                    "rule": "unclosed-fence",
                    "text": "code fence has no closing line; "
                            "the rest of the file was not checked"})
    return out


def _files(paths: list[Path]) -> list[Path]:
    out = []
    for p in map(Path, paths):
        if p.is_dir():
            out.extend(sorted(p.rglob("*.md")))
        else:
            out.append(p)
    return out


def lint_paths(paths: list[Path], glossary: Path | None) -> list[dict]:
    """Lint each file, and each `*.md` file under each directory.

    The glossary file itself is never checked for its own synonyms.
    Raises FileNotFoundError for a path that does not exist.
    """
    synonyms = load_glossary(glossary)
    own = Path(glossary).resolve() if glossary else None
    out = []
    for f in _files(paths):
        if not f.exists():
            raise FileNotFoundError(str(f))
        try:
            text = f.read_bytes().decode("utf-8-sig")
        except UnicodeDecodeError:
            out.append({"path": str(f), "line": 1, "rule": "encoding",
                        "text": "file is not UTF-8; it was not checked"})
            continue
        use = {} if own is not None and f.resolve() == own else synonyms
        out.extend(lint_text(text, str(f), use))
    return out


def format_row(row: dict) -> str:
    """`file:line: rule: text`, the CLI output format."""
    return f"{row['path']}:{row['line']}: {row['rule']}: {row['text']}"
