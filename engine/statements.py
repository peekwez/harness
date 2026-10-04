"""Verification statements and the test links that prove them (spec 6.1, 6.2).

A statement is one line, `V-<feature>-<n>: <statement>`, in
`explore/VERIFY.md` or, without explore, in the working document's
verification matrix. `harness compile` writes the statements to
`.harness/verify.jsonl`. A test links to a statement with a comment in any
comment syntax: `verifies: V-orders-3  kills: <the bug the test catches>`.
"""
from __future__ import annotations

import os
import re
import subprocess
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

from . import (HarnessError, SubstrateMissing, harness_dir, load_backlog,
               read_jsonl, write_jsonl)

STATEMENT_ID = re.compile(r"V-[a-z0-9-]+-[0-9]+")
VERIFY_MD = "explore/VERIFY.md"
VERIFY_JSONL = "verify.jsonl"

_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_STATEMENT_LINE = re.compile(
    r"^\s*(?:#{1,6}\s+|(?:[-*+]|\d+[.)])\s+)?(?:\*\*|`)?"
    r"(?P<id>V-[A-Za-z0-9_.-]+?)(?:\*\*|`)?\s*:(?:\*\*)?\s*(?P<text>.*?)\s*$")
_LOOKS_LIKE_ID = re.compile(r"V-[A-Za-z0-9_.-]+-[0-9]+")

# Comment openers and closers for the languages harness repos use.
_MARKER = r"(?:#+|//+|--|;+|%+|/\*+|\*|<!--|\(\*|\{-)"
_CLOSER = r"(?:\*+/|-->|\*\)|-\})"
_LINK = re.compile(
    rf"(?:^|\s){_MARKER}\s*verifies:\s*(?P<ids>.*?)"
    rf"(?:\s+kills:\s*(?P<kills>.*?))?\s*{_CLOSER}?\s*$")
_KILLS_LINE = re.compile(
    rf"^\s*{_MARKER}\s*kills:\s*(?P<kills>.*?)\s*{_CLOSER}?\s*$")

TEST_DIRS = ("tests/*", "*/tests/*", "test/*", "*/test/*", "spec/*",
             "*/spec/*", "__tests__/*", "*/__tests__/*")
TEST_NAMES = ("test_*", "*_test.*", "*.test.*", "*.spec.*", "*_spec.*",
              "conftest.py")
SKIP_DIRS = {".git", ".harness", ".worktrees", "node_modules", ".venv",
             "venv", "__pycache__"}
MAX_SCAN_BYTES = 1_000_000


def statement_key(sid: str) -> tuple:
    """Sort key: feature, then the number as an integer."""
    feature, _, number = sid[2:].rpartition("-")
    return (feature, int(number) if number.isdigit() else 0, sid)


def parse_statements(text: str, source: str) -> list[dict]:
    """Statement rows from one document.

    Args:
        text: The document text.
        source: Repo-relative path, used in each row and in errors.

    Returns:
        Rows `{"id", "feature", "statement", "source"}` in document order.

    Raises:
        HarnessError: A line has a malformed ID (for example `V-Orders-3`),
            an empty statement, or an ID that an earlier line uses.
    """
    rows, seen, fence = [], {}, None
    for lineno, line in enumerate(text.splitlines(), 1):
        opener = _FENCE.match(line)
        if opener:
            marker = opener.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence is not None:
            continue
        match = _STATEMENT_LINE.match(line)
        if not match:
            continue
        sid, statement = match.group("id"), match.group("text")
        if not STATEMENT_ID.fullmatch(sid):
            if _LOOKS_LIKE_ID.fullmatch(sid):
                raise HarnessError(
                    f"{source}:{lineno}: statement ID {sid!r} does not match "
                    f"V-[a-z0-9-]+-[0-9]+. Use lowercase letters, digits and "
                    f"dashes.")
            continue
        if not statement:
            raise HarnessError(f"{source}:{lineno}: statement {sid} has no "
                               f"text. Write the statement after the colon.")
        if sid in seen:
            raise HarnessError(f"{source}:{lineno}: statement ID {sid} is also "
                               f"on line {seen[sid]}. Give each statement its "
                               f"own ID.")
        seen[sid] = lineno
        rows.append({"id": sid, "feature": sid[2:].rpartition("-")[0],
                     "statement": statement, "source": source})
    return rows


def load_statements(root) -> list[dict]:
    """Rows of `.harness/verify.jsonl`; an empty list when it is absent."""
    return read_jsonl(harness_dir(root) / VERIFY_JSONL)


def parse_id_list(values) -> list[str]:
    """Statement IDs from CLI values, split on commas and whitespace.

    Raises:
        HarnessError: A value is not `V-<feature>-<n>`.
    """
    out = []
    for value in values or []:
        for token in re.split(r"[,\s]+", str(value)):
            if not token:
                continue
            if not STATEMENT_ID.fullmatch(token):
                raise HarnessError(f"statement ID {token!r} does not match "
                                   f"V-[a-z0-9-]+-[0-9]+. Use a lowercase ID "
                                   f"such as V-orders-3.")
            if token not in out:
                out.append(token)
    return out


def unowned_statements(root, rows) -> list[str]:
    """Statement IDs in `verify.jsonl` that no slice row lists in `verifies`."""
    owned = {sid for row in rows for sid in (row.get("verifies") or [])}
    return sorted((r["id"] for r in load_statements(root)
                   if r["id"] not in owned), key=statement_key)


def is_test_path(rel: str) -> bool:
    """True when a repo-relative path looks like a test file."""
    posix = PurePosixPath(str(rel).replace("\\", "/"))
    text, name = posix.as_posix(), posix.name
    return (any(fnmatch(text, pat) for pat in TEST_DIRS)
            or any(fnmatch(name, pat) for pat in TEST_NAMES))


def expand_suite(root, patterns) -> list[str]:
    """Repo-relative files named by acceptance patterns.

    Globs expand against the root. A directory expands to every file under
    it. A path that does not exist is left out: the acceptance runner
    reports missing paths, not this helper.
    """
    root = Path(root)
    out = set()
    for pat in patterns or []:
        hits = (list(root.glob(pat)) if any(c in pat for c in "*?[")
                else [root / pat])
        for hit in hits:
            if hit.is_dir():
                out.update(f.relative_to(root).as_posix()
                           for f in hit.rglob("*")
                           if f.is_file() and "__pycache__" not in f.parts)
            elif hit.is_file():
                out.add(hit.relative_to(root).as_posix())
    return sorted(out)


def _repo_files(root: Path) -> list[str]:
    proc = subprocess.run(["git", "-C", str(root), "ls-files", "--cached",
                           "--others", "--exclude-standard", "-z"],
                          capture_output=True, text=True)
    if proc.returncode == 0:
        files = [f for f in proc.stdout.split("\0") if f]
    else:
        files = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            files.extend(Path(dirpath, fn).relative_to(root).as_posix()
                         for fn in filenames)
    return [f for f in files if PurePosixPath(f).parts[0] not in SKIP_DIRS]


def linked_test_files(root) -> list[str]:
    """Files that may carry test links: test files plus acceptance files."""
    root = Path(root)
    try:
        rows = load_backlog(root)
    except SubstrateMissing:
        rows = []
    patterns = [p for row in rows for p in (row.get("acceptance") or [])]
    tests = {f for f in _repo_files(root) if is_test_path(f)}
    return sorted(tests | set(expand_suite(root, patterns)))


def _read_lines(path: Path):
    try:
        if path.stat().st_size > MAX_SCAN_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace").splitlines()


def scan_test_links(root, paths) -> dict[str, list[dict]]:
    """Statement ID -> the test comments that name it.

    Args:
        root: Repo root.
        paths: Repo-relative files to scan. Missing, binary and files over
            1 MB are skipped.

    Returns:
        `{id: [{"path", "line", "kills"}]}`. `kills` is None when the
        comment and the next comment line carry no `kills:` text. Keys are
        every token after `verifies:`, so a mistyped ID is a key too.
    """
    root = Path(root)
    links: dict = {}
    for rel in sorted({Path(str(p)).as_posix() for p in paths}):
        lines = _read_lines(root / rel)
        if lines is None:
            continue
        for index, line in enumerate(lines):
            match = _LINK.search(line)
            if not match:
                continue
            ids = [t for t in re.split(r"[,\s]+", match.group("ids")) if t]
            kills = (match.group("kills") or "").strip()
            if not kills and index + 1 < len(lines):
                follow = _KILLS_LINE.match(lines[index + 1])
                if follow:
                    kills = follow.group("kills").strip()
            for sid in ids:
                links.setdefault(sid, []).append(
                    {"path": rel, "line": index + 1, "kills": kills or None})
    return links


def compile_statements(root, working_doc=None) -> dict:
    """Write `.harness/verify.jsonl` and report unknown test links.

    The source is `explore/VERIFY.md` when it exists. Otherwise it is the
    working document, when it holds at least one statement. With no source,
    an existing `verify.jsonl` stays as it is.

    Returns:
        `{"source", "statements", "unknown_links", "warnings"}`.

    Raises:
        HarnessError: From `parse_statements`. Nothing is written then.
    """
    root = Path(root)
    out = {"source": None, "statements": [], "unknown_links": [],
           "warnings": []}
    target = harness_dir(root) / VERIFY_JSONL
    rows, source = None, None
    verify_md = root / VERIFY_MD
    if verify_md.is_file():
        source = VERIFY_MD
        rows = parse_statements(verify_md.read_text(encoding="utf-8"), source)
        if not rows:
            out["warnings"].append(f"{VERIFY_MD}: no statements found. Write "
                                   f"lines like V-orders-1: <statement>.")
    elif working_doc is not None:
        from .docsections import doc_ref_for
        doc_source = doc_ref_for(root, working_doc)
        doc_rows = parse_statements(
            Path(working_doc).read_text(encoding="utf-8"), doc_source)
        if doc_rows:
            source, rows = doc_source, doc_rows
    if rows is not None:
        write_jsonl(target, sorted(rows, key=lambda r: statement_key(r["id"])))
        out["source"] = source
    elif not target.exists():
        return out
    known = {r["id"] for r in load_statements(root)}
    out["statements"] = sorted(known, key=statement_key)
    for sid, found in sorted(scan_test_links(
            root, linked_test_files(root)).items()):
        if sid in known:
            continue
        for link in found:
            out["unknown_links"].append({"id": sid, **link})
            out["warnings"].append(
                f"UNKNOWN_TEST_LINK: {link['path']}:{link['line']}: {sid} is "
                f"not in .harness/verify.jsonl. Fix the ID, or add the "
                f"statement and compile.")
    return out
