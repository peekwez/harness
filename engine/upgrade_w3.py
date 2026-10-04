"""Harness 0.10 upgrade steps owned by W3: shared memory (spec section 12,
steps 3, 6 and 13; D-0.10-02).

Retire `.harness/memory/` after exporting its durable rows for human review,
drop its git lines, scaffold `.claude/memory/shared/MEMORY.md`, and add the
shared-memory import to a harness-marked CLAUDE.md. Upgrade never promotes:
promotion is a human choice (spec section 8). Each step is idempotent: after
`apply`, `describe` returns [].
"""
from __future__ import annotations

import hashlib
import json
import re
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import HarnessError, jsonl_lines
from .shared_memory import (CLAUDE_IMPORT, INDEX_REL, _write_atomic,
                            add_claude_import, claude_md_state, ensure_index)
from .upgrade_010 import SKIPPED, Ask, Step, register, write_lines

MEMORY_DIR = ".harness/memory"
CACHE_DIR = ".harness/cache"
LEGACY_DIR = f"{CACHE_DIR}/legacy-memory"
EXPORT_REL = f"{CACHE_DIR}/durable-memory-export.md"
OFFERED_KINDS = ("attempt", "adjudication")
ROW_MARK = "<!-- harness-export-row: "
LEGACY_ATTR = (".harness/memory/durable.jsonl", "merge=union")
LEGACY_IGNORE = ".harness/memory/session"
SHARED_GATE_ID = "G10"
RETIRE_ID = "w3.retire-durable-memory"


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)


def _lines(path: Path) -> list:
    return jsonl_lines(path.read_text(encoding="utf-8")) if path.exists() else []


# ------------------------------------------------- retire .harness/memory/
def _memory_files(root: Path) -> list:
    """durable.jsonl, then session/*.jsonl (0.9 working memory)."""
    mem = root / MEMORY_DIR
    files = [mem / "durable.jsonl"] if (mem / "durable.jsonl").is_file() else []
    if (mem / "session").is_dir():
        files += sorted(p for p in (mem / "session").glob("*.jsonl")
                        if p.is_file())
    return files


def _read_rows(root: Path, path: Path) -> list:
    """Rows of one legacy JSONL file.

    Raises:
        HarnessError: the file is not UTF-8 or a line is not JSON.
    """
    rel = path.relative_to(root).as_posix()
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HarnessError(
            f"{RETIRE_ID}: {rel} is not valid UTF-8. Fix the file, then run: "
            f"harness upgrade") from exc
    rows = []
    # only \n ends a row: append_jsonl keeps U+2028, U+2029 and U+0085 raw,
    # and splitlines() would cut a row at each of them
    for lineno, line in enumerate(text.split("\n"), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise HarnessError(
                f"{RETIRE_ID}: {rel} line {lineno} is not valid JSON. Fix or "
                f"delete the line, then run: harness upgrade") from exc
    return rows


def _kept(row) -> bool:
    """The rows 0.9 kept on purpose: attempts, adjudications and reasoning
    marked `promote`. Close-summary observations are noise."""
    if not isinstance(row, dict):
        return False
    kind = row.get("kind")
    return (kind in OFFERED_KINDS
            or (kind == "reasoning" and row.get("promote") is True))


def _row_key(row: dict, text: str) -> str:
    rid = row.get("id")
    if isinstance(rid, str) and rid.strip():
        return " ".join(rid.split())
    return "sha-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _offered(root: Path) -> list:
    """[(key, row, text)] for every kept row, first occurrence of each key."""
    out, seen = [], set()
    for path in _memory_files(root):
        for row in _read_rows(root, path):
            if not _kept(row):
                continue
            text = _fact_text(row)
            if not text:
                continue
            key = _row_key(row, text)
            if key not in seen:
                seen.add(key)
                out.append((key, row, text))
    return out


def _journals(root: Path) -> list:
    """Interrupted close journals at the 0.9 path."""
    session = root / MEMORY_DIR / "session"
    return sorted(session.glob(".close-*.json")) if session.is_dir() else []


def _tracked(root: Path) -> list:
    proc = _git(root, "ls-files", "--", MEMORY_DIR)
    return [p for p in proc.stdout.splitlines() if p] if proc.returncode == 0 else []


def _fact_text(row: dict) -> str:
    text = " ".join(str(row.get("content") or "").split())
    attempt = row.get("attempt")
    if row.get("kind") == "attempt" and isinstance(attempt, dict):
        for key in ("approach", "outcome", "why"):
            value = " ".join(str(attempt.get(key) or "").split()).rstrip(".")
            if value:
                text += f" {key.capitalize()}: {value}."
    return text.strip()


def _section(key: str, row: dict, text: str) -> str:
    command = f"harness memory promote --text {shlex.quote(text)}"
    longest = max((len(run) for run in re.findall(r"`+", command)), default=0)
    fence = "`" * max(3, longest + 1)
    return "\n".join([f"{ROW_MARK}{key} -->",
                      f"## {key} ({row.get('kind')})", "", f"> {text}", "",
                      f"{fence}bash", command, fence, "", ""])


_EXPORT_HEAD = ("# Durable memory from harness 0.9\n\n"
                "Review each fact. To share one with the team, run its "
                "command.\nDelete this file when you are done.\n\n")


def _write_export(root: Path, offered: list) -> int:
    """Merge offered rows into the export by key. Rows already in the file
    stay as they are. Returns the number of rows added."""
    path = root / EXPORT_REL
    text = path.read_text(encoding="utf-8") if path.exists() else _EXPORT_HEAD
    present = {line[len(ROW_MARK):].rsplit(" -->", 1)[0]
               for line in text.splitlines() if line.startswith(ROW_MARK)}
    added = [_section(k, r, t) for k, r, t in offered if k not in present]
    if not added:
        return 0
    if not text.endswith("\n"):
        text += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(path, text + "".join(added))
    return len(added)


def _stamp_dir(root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target, n = root / LEGACY_DIR / stamp, 1
    while target.exists():
        target = root / LEGACY_DIR / f"{stamp}-{n}"
        n += 1
    return target


def describe_retire(root) -> list:
    root = Path(root)
    if not (root / MEMORY_DIR).exists():
        return []
    try:
        offered = _offered(root)
    except HarnessError as exc:
        return [str(exc)]       # apply raises the same error before any change
    lines = []
    if offered:
        lines.append(f"export {len(offered)} memory rows to {EXPORT_REL} "
                     f"for review")
    journals = _journals(root)
    if journals:
        lines.append(f"move {len(journals)} interrupted close journals to "
                     f"{CACHE_DIR}/")
    tracked = _tracked(root)
    if tracked:
        lines.append(f"untrack {len(tracked)} files under {MEMORY_DIR}/")
    lines.append(f"move {MEMORY_DIR}/ to {LEGACY_DIR}/<stamp>/")
    return lines


def apply_retire(root, ask: Ask) -> list:
    root = Path(root)
    if not (root / MEMORY_DIR).exists():
        return []
    offered = _offered(root)          # a bad file raises before any change
    if not ask(f"Move {MEMORY_DIR}/ to {LEGACY_DIR}/<stamp>/? Harness first "
               f"exports attempt, adjudication and promoted reasoning rows to "
               f"{EXPORT_REL}."):
        return [SKIPPED]
    report = []
    if offered:
        added = _write_export(root, offered)
        report.append(f"exported {added} new rows to {EXPORT_REL}")
    cache = root / CACHE_DIR
    for journal in _journals(root):
        target = cache / journal.name.lstrip(".")
        if target.exists():
            report.append(f"kept {journal.name} in the moved tree; "
                          f"{CACHE_DIR}/{target.name} exists")
            continue
        cache.mkdir(parents=True, exist_ok=True)
        journal.replace(target)
        report.append(f"moved {journal.name} to {CACHE_DIR}/{target.name}")
    tracked = _tracked(root)
    if tracked:
        proc = _git(root, "rm", "-r", "-q", "--cached", "--ignore-unmatch",
                    "--", MEMORY_DIR)
        if proc.returncode != 0:
            raise HarnessError(
                f"{RETIRE_ID}: git rm --cached {MEMORY_DIR} failed: "
                f"{proc.stderr.strip()}. Fix the index, then run: "
                f"harness upgrade")
        report.append(f"untracked {len(tracked)} files under {MEMORY_DIR}/")
    target = _stamp_dir(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(root / MEMORY_DIR), str(target))
    report.append(f"moved {MEMORY_DIR}/ to "
                  f"{target.relative_to(root).as_posix()}/")
    return report


def advise_retire(root) -> list:
    if not (Path(root) / EXPORT_REL).exists():
        return []
    return [f"check: review {EXPORT_REL}. Promote the facts you want with its "
            f"commands, then delete the file."]


# ------------------------------------------------------------- git lines
def _is_legacy_attr(line: str) -> bool:
    tokens = line.split()
    return (len(tokens) == 2 and tokens[0].lstrip("/") == LEGACY_ATTR[0]
            and tokens[1] == LEGACY_ATTR[1])


def _is_legacy_ignore(line: str) -> bool:
    tokens = line.split()
    return len(tokens) == 1 and tokens[0].strip("/") == LEGACY_IGNORE


def _pending_git_lines(root: Path, *, preview: bool = False) -> list:
    """[(file name, matcher, line)] for each legacy line still present.

    Both lines stay while the legacy folder exists (a declined retire): the
    union driver still merges a tracked durable.jsonl, and the ignore line
    still hides session files. `preview` lists them anyway, for the dry run.
    """
    if (root / MEMORY_DIR).exists() and not preview:
        return []
    return ([(".gitattributes", _is_legacy_attr, line)
             for line in _lines(root / ".gitattributes")
             if _is_legacy_attr(line)]
            + [(".gitignore", _is_legacy_ignore, line)
               for line in _lines(root / ".gitignore")
               if _is_legacy_ignore(line)])


def describe_git_lines(root) -> list:
    return [f"remove '{line.strip()}' from {name}"
            for name, _match, line in _pending_git_lines(Path(root))]


def preview_git_lines(root) -> list:
    """The dry run: the lines go after w3.retire-durable-memory moves the folder."""
    root = Path(root)
    if not (root / MEMORY_DIR).exists():
        return describe_git_lines(root)
    return [f"remove '{line.strip()}' from {name} (after w3.retire-durable-memory)"
            for name, _match, line in _pending_git_lines(root, preview=True)]


def apply_git_lines(root, ask: Ask) -> list:
    root = Path(root)
    report = []
    for name in (".gitattributes", ".gitignore"):
        hits = [(m, line) for n, m, line in _pending_git_lines(root) if n == name]
        if not hits:
            continue
        match = hits[0][0]
        path = root / name
        kept = [line for line in _lines(path) if not match(line)]
        write_lines(path, kept)
        report += [f"removed '{line.strip()}' from {name}" for _m, line in hits]
    return report


# ---------------------------------------------------------- shared index
def describe_index(root) -> list:
    return [] if (Path(root) / INDEX_REL).exists() else [f"create {INDEX_REL}"]


def apply_index(root, ask: Ask) -> list:
    return [f"created {INDEX_REL}"] if ensure_index(root) else []


def advise_index(root) -> list:
    """A `gates.extra` gate with id G10 no longer loads: G10 is built in.

    Each entry loads on its own. An entry that fails or exits at import
    gets no advice here; the gate loader reports it.
    """
    import copy

    from . import load_config
    from .gates import reserved_gate_ids
    from .gates.extra import extra_entries, load_extra_gates
    try:
        config = load_config(root)
        entries = extra_entries(config)
    except (HarnessError, TypeError):
        return []
    reserved = reserved_gate_ids() - {SHARED_GATE_ID}
    out = []
    for entry in entries:
        one = copy.deepcopy(config)
        one.setdefault("gates", {})["extra"] = [entry]
        try:
            gates, _errors = load_extra_gates(root, one, reserved_ids=reserved)
        except (Exception, SystemExit):  # noqa: BLE001 - consumer code
            continue
        out += [f"check: gates.extra entry {gate.entry} declares id "
                f"{SHARED_GATE_ID}, now a built-in gate. Rename its GATE id."
                for gate in gates if gate.GATE.get("id") == SHARED_GATE_ID]
    return out


# ------------------------------------------------------------- CLAUDE.md
def describe_claude(root) -> list:
    if claude_md_state(root) == "marked":
        return [f"add {CLAUDE_IMPORT} to CLAUDE.md"]
    return []          # missing or unmarked: not ours to write, see advise


def apply_claude(root, ask: Ask) -> list:
    if add_claude_import(root):
        return [f"added {CLAUDE_IMPORT} to CLAUDE.md"]
    return []


def advise_claude(root) -> list:
    state = claude_md_state(root)
    if state == "missing":
        return [f"check: no CLAUDE.md. To load shared memory, create one "
                f"with this line: {CLAUDE_IMPORT}"]
    if state == "unmarked":
        return [f"check: CLAUDE.md has no harness marker, so harness does not "
                f"edit it. Add this line by hand: {CLAUDE_IMPORT}"]
    return []


register(Step(
    id="w3.retire-durable-memory",
    title="Export kept memory rows for review, then move .harness/memory/ "
          "to .harness/cache/legacy-memory/.",
    describe=describe_retire, apply=apply_retire, destructive=True,
    advise=advise_retire))
register(Step(
    id="w3.memory-git-lines",
    title="Remove .harness/memory/ lines from .gitattributes and .gitignore.",
    describe=describe_git_lines, apply=apply_git_lines, preview=preview_git_lines))
register(Step(
    id="w3.shared-memory-index",
    title="Create the shared memory index .claude/memory/shared/MEMORY.md.",
    describe=describe_index, apply=apply_index, advise=advise_index))
register(Step(
    id="w3.claude-md-import",
    title="Add the shared memory import to a harness CLAUDE.md.",
    describe=describe_claude, apply=apply_claude, advise=advise_claude))
