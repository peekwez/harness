"""Harness 0.10 upgrade steps owned by W3: shared memory (spec section 12,
steps 3, 6 and 13; D-0.10-02).

Retire `.harness/memory/` after exporting its durable rows for human review,
drop its git lines, scaffold `.claude/memory/shared/MEMORY.md`, and add the
shared-memory import to a harness-marked CLAUDE.md. Upgrade never promotes:
promotion is a human choice (spec section 8). Each step is idempotent: after
`apply`, `describe` returns [].
"""
from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

from . import HarnessError, read_jsonl
from .shared_memory import (CLAUDE_IMPORT, INDEX_REL, add_claude_import,
                            claude_md_state, ensure_index)
from .upgrade_010 import SKIPPED, Ask, Step, register

MEMORY_DIR = ".harness/memory"
CACHE_DIR = ".harness/cache"
EXPORT_REL = f"{CACHE_DIR}/durable-memory-export.md"
OFFERED_KINDS = ("attempt", "adjudication")
LEGACY_ATTR = (".harness/memory/durable.jsonl", "merge=union")
LEGACY_IGNORE = ".harness/memory/session"
SHARED_GATE_ID = "G10"


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)


def _lines(path: Path) -> list:
    return path.read_text().splitlines() if path.exists() else []


# ------------------------------------------------- retire .harness/memory/
def _offered(root: Path) -> list:
    """The `attempt` and `adjudication` rows 0.9 kept on purpose.

    Close-summary `observation` rows are noise; git history keeps them.
    """
    path = root / MEMORY_DIR / "durable.jsonl"
    try:
        rows = read_jsonl(path)
    except HarnessError as exc:
        raise HarnessError(
            f"w3.retire-durable-memory: cannot read {MEMORY_DIR}/durable.jsonl: "
            f"{exc}. Fix the line, then run: harness upgrade") from exc
    return [r for r in rows if isinstance(r, dict)
            and r.get("kind") in OFFERED_KINDS
            and str(r.get("content") or "").strip()]


def _journals(root: Path) -> list:
    """Interrupted close journals at the 0.9 path."""
    session = root / MEMORY_DIR / "session"
    return sorted(session.glob(".close-*.json")) if session.is_dir() else []


def _tracked(root: Path) -> list:
    proc = _git(root, "ls-files", "--", MEMORY_DIR)
    return [p for p in proc.stdout.splitlines() if p] if proc.returncode == 0 else []


def _fact_text(row: dict) -> str:
    text = " ".join(str(row.get("content", "")).split())
    attempt = row.get("attempt")
    if row.get("kind") == "attempt" and isinstance(attempt, dict):
        for key in ("approach", "outcome", "why"):
            value = " ".join(str(attempt.get(key) or "").split()).rstrip(".")
            if value:
                text += f" {key.capitalize()}: {value}."
    return text


def _write_export(root: Path, rows: list) -> None:
    """Write offered rows as review notes, each with a ready promote command."""
    out = ["# Durable memory from harness 0.9", "",
           "Review each fact. To share one with the team, run its command.",
           "Delete this file when you are done.", ""]
    for row in rows:
        text = _fact_text(row)
        out += [f"## {row.get('id')} ({row.get('kind')})", "", text, "",
                "```bash", f"harness memory promote --text {shlex.quote(text)}",
                "```", ""]
    path = root / EXPORT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out))


def describe_retire(root) -> list:
    root = Path(root)
    if not (root / MEMORY_DIR).exists():
        return []
    lines = []
    offered = _offered(root)
    if offered:
        lines.append(f"export {len(offered)} durable memory rows to "
                     f"{EXPORT_REL} for review")
    journals = _journals(root)
    if journals:
        lines.append(f"move {len(journals)} interrupted close journals to "
                     f"{CACHE_DIR}/")
    tracked = _tracked(root)
    if tracked:
        lines.append(f"untrack {len(tracked)} files under {MEMORY_DIR}/")
    lines.append(f"delete {MEMORY_DIR}/; git history keeps it")
    return lines


def apply_retire(root, ask: Ask) -> list:
    root = Path(root)
    if not (root / MEMORY_DIR).exists():
        return []
    offered = _offered(root)
    if not ask(f"Delete {MEMORY_DIR}/? Harness exports its attempt and "
               f"adjudication rows to {EXPORT_REL} first. Git history keeps "
               f"the rest."):
        return [SKIPPED]
    report = []
    if offered:
        _write_export(root, offered)
        report.append(f"exported {len(offered)} rows to {EXPORT_REL}")
    cache = root / CACHE_DIR
    for journal in _journals(root):
        target = cache / journal.name.lstrip(".")
        if target.exists():
            report.append(f"kept the newer {target.name} in {CACHE_DIR}/")
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
                f"w3.retire-durable-memory: git rm --cached {MEMORY_DIR} "
                f"failed: {proc.stderr.strip()}. Fix the index, then run: "
                f"harness upgrade")
        report.append(f"untracked {len(tracked)} files under {MEMORY_DIR}/")
    shutil.rmtree(root / MEMORY_DIR)
    report.append(f"deleted {MEMORY_DIR}/")
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


def _pending_git_lines(root: Path) -> list:
    """[(file name, matcher, line)] for each legacy line still present."""
    pending = [(".gitattributes", _is_legacy_attr, line)
               for line in _lines(root / ".gitattributes")
               if _is_legacy_attr(line)]
    # keep the ignore line while session files may still exist
    if not (root / MEMORY_DIR).exists():
        pending += [(".gitignore", _is_legacy_ignore, line)
                    for line in _lines(root / ".gitignore")
                    if _is_legacy_ignore(line)]
    return pending


def describe_git_lines(root) -> list:
    return [f"remove '{line.strip()}' from {name}"
            for name, _match, line in _pending_git_lines(Path(root))]


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
        path.write_text("\n".join(kept) + "\n" if kept else "")
        report += [f"removed '{line.strip()}' from {name}" for _m, line in hits]
    return report


# ---------------------------------------------------------- shared index
def describe_index(root) -> list:
    return [] if (Path(root) / INDEX_REL).exists() else [f"create {INDEX_REL}"]


def apply_index(root, ask: Ask) -> list:
    return [f"created {INDEX_REL}"] if ensure_index(root) else []


def advise_index(root) -> list:
    """A `gates.extra` gate with id G10 no longer loads: G10 is built in."""
    from . import load_config
    from .gates import reserved_gate_ids
    from .gates.extra import load_extra_gates
    try:
        config = load_config(root)
    except HarnessError:
        return []
    reserved = reserved_gate_ids() - {SHARED_GATE_ID}
    gates, _errors = load_extra_gates(root, config, reserved_ids=reserved)
    return [f"check: gates.extra entry {gate.entry} declares id "
            f"{SHARED_GATE_ID}, now a built-in gate. Rename its GATE id."
            for gate in gates if gate.GATE.get("id") == SHARED_GATE_ID]


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
    title="Export durable memory rows for review, then delete .harness/memory/.",
    describe=describe_retire, apply=apply_retire, destructive=True,
    advise=advise_retire))
register(Step(
    id="w3.memory-git-lines",
    title="Remove .harness/memory/ lines from .gitattributes and .gitignore.",
    describe=describe_git_lines, apply=apply_git_lines))
register(Step(
    id="w3.shared-memory-index",
    title="Create the shared memory index .claude/memory/shared/MEMORY.md.",
    describe=describe_index, apply=apply_index, advise=advise_index))
register(Step(
    id="w3.claude-md-import",
    title="Add the shared memory import to a harness CLAUDE.md.",
    describe=describe_claude, apply=apply_claude, advise=advise_claude))
