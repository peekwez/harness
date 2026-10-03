"""Shared memory (D-0.10-02): team facts that a human promoted.

Harness manages only `.claude/memory/shared/`. Personal agent memory stays
with the host (Claude Code auto memory). Harness reads its location only to
list the files that changed during a slice, so a human can promote them.
"""
from __future__ import annotations

import json
import os
import posixpath
import re
import subprocess
from pathlib import Path

from . import HarnessError, get_slice, now_iso

SHARED_DIR = ".claude/memory/shared"
INDEX_NAME = "MEMORY.md"
INDEX_REL = f"{SHARED_DIR}/{INDEX_NAME}"
CLAUDE_IMPORT = "@.claude/memory/shared/MEMORY.md"
CLAUDE_MARKER = "harness-enforced"
MAX_INDEX_LINE = 120
MAX_SLUG = 50
ENTRY_WARN_LIMIT = 40
INDEX_HEADER = (
    "# Shared memory\n\n"
    "Team facts. A human adds each one with `harness memory promote`.\n"
    "Agents read this file. Agents do not edit it.\n\n")
# The harness template line: "This repo is harness-enforced. ..." (optionally
# after a heading such as "# AGENTS.md — "). Line-anchored, not a substring.
_MARKER_LINE = re.compile(
    r"^(?:#+ .*?— )?this repo is " + re.escape(CLAUDE_MARKER) + r"\b",
    re.I | re.M)
_SHARED_SEGMENT = "/" + SHARED_DIR.casefold() + "/"


# ------------------------------------------------------------------ paths
def in_shared_dir(rel: str) -> bool:
    """True when a repo-relative path is in, or is, the shared folder.

    Case-insensitive (macOS file systems are), traversal-normalized, and
    matched anywhere in the path so a slice worktree prefix still counts.
    Absolute paths are outside the repo after event normalization.
    """
    path = str(rel).replace("\\", "/")
    if path.startswith("/"):
        return False
    norm = "/" + posixpath.normpath(path).casefold() + "/"
    return _SHARED_SEGMENT in norm


# ------------------------------------------------------------------ index
def ensure_index(root) -> bool:
    """Create `shared/MEMORY.md` with its header. True when it was created."""
    index = Path(root) / INDEX_REL
    if index.exists():
        return False
    index.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(index, INDEX_HEADER)
    return True


def index_entries(root) -> list:
    """The `- [title](file.md) — summary` lines of the shared index."""
    index = Path(root) / INDEX_REL
    if not index.exists():
        return []
    return [line for line in index.read_text(encoding="utf-8").splitlines()
            if line.startswith("- [")]


def slugify(text: str) -> str:
    """File-name slug: lowercase ASCII words joined by `-`, 50 chars max."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    if len(slug) > MAX_SLUG:
        cut = slug[:MAX_SLUG]
        slug = (cut.rsplit("-", 1)[0] if "-" in cut else cut).strip("-")
    return slug or "fact"


def _write_atomic(path: Path, content: str) -> None:
    """Write through a temp file and `os.replace` so readers never see half."""
    tmp = path.with_name(f".{path.name}.tmp{os.getpid()}")
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _one_line(text: str) -> str:
    return " ".join(str(text).split())


def _first_line(body: str) -> str:
    for line in body.splitlines():
        line = line.strip().lstrip("#").strip()
        if line.startswith(("- ", "* ")):
            line = line[2:].strip()
        if line:
            return line
    return ""


def index_line(title: str, slug: str, summary: str) -> str:
    """One index line of MAX_INDEX_LINE characters or fewer.

    The link part stays whole: the title is cut first (to keep the link
    within 80 characters), then the summary.
    """
    title = _one_line(title).replace("[", "(").replace("]", ")")
    frame = len(f"- []({slug}.md)")
    if frame + len(title) > 80:
        title = title[:max(1, 80 - frame - 1)].rstrip() + "…"
    head = f"- [{title}]({slug}.md)"
    summary = _one_line(summary)
    line = f"{head} — {summary}" if summary else head
    if len(line) > MAX_INDEX_LINE:
        line = line[:MAX_INDEX_LINE - 1].rstrip() + "…"
    return line


def _add_index_line(root, line: str, slug: str) -> bool:
    ensure_index(root)
    index = Path(root) / INDEX_REL
    text = index.read_text(encoding="utf-8")
    if f"]({slug}.md)" in text:
        return False
    if text and not text.endswith("\n"):
        text += "\n"
    _write_atomic(index, text + line + "\n")
    return True


# ------------------------------------------------------------------ facts
def split_front_matter(text: str) -> tuple:
    """`(meta, body)`. Text without valid YAML front matter -> `({}, text)`.

    Accepts CRLF line endings and empty front matter. The closing line must
    be exactly `---`.
    """
    text = text.replace("\r\n", "\n")
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        match = re.search(r"^---[ \t]*$", text[4:], re.M)
        if match:
            import yaml
            try:
                meta = yaml.safe_load(text[4:4 + match.start()]) or {}
            except yaml.YAMLError:
                meta = None
            if isinstance(meta, dict):
                return meta, text[4 + match.end():].lstrip("\n")
    return {}, text


def _render_fact(meta: dict, body: str) -> str:
    import yaml
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True,
                           width=1000)
    return f"---\n{front}---\n\n{body.strip()}\n"


def git_identity(root) -> str:
    """`Name <email>` from git config. Fails when `user.name` is not set."""
    def cfg(key):
        proc = subprocess.run(["git", "-C", str(root), "config", key],
                              capture_output=True, text=True)
        return proc.stdout.strip() if proc.returncode == 0 else ""
    name, email = cfg("user.name"), cfg("user.email")
    if not name:
        raise HarnessError(
            "memory promote: git user.name is not set. "
            "Fix: git config user.name \"<your name>\".")
    return f"{name} <{email}>" if email else name


def promote(root, *, source=None, text=None, name=None) -> dict:
    """Copy one fact into the shared folder and index it.

    Args:
        root: Substrate root.
        source: A memory file (front matter optional). Mutually exclusive
            with `text`.
        text: The fact itself.
        name: File-name override (slugified).

    Returns:
        `{"promoted": True, "path", "promoted_by", "promoted_at",
        "index_line", "entries"}`, or `{"promoted": False, "reason":
        "already shared", "path", "index_line_added"}` when the same fact
        is already in the folder.

    Raises:
        HarnessError: no fact, two facts, an empty fact, an index file, a
            missing file, no git identity, or a different fact already
            under the same name.
    """
    root = Path(root)
    if (source is None) == (text is None):
        raise HarnessError(
            "memory promote: pass one fact. Fix: give a file or --text \"<fact>\".")
    meta, body = {}, ""
    if source is not None:
        source = Path(source).expanduser().resolve()
        if not source.is_file():
            raise HarnessError(
                f"memory promote: file not found: {source}. "
                f"Fix: pass the path of one memory file.")
        if source.name == INDEX_NAME:
            raise HarnessError(
                f"memory promote: {source.name} is an index, not a fact. "
                f"Fix: promote one fact file.")
        try:
            raw = source.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as err:
            raise HarnessError(
                f"memory promote: cannot read {source} as UTF-8 text ({err.__class__.__name__}). "
                f"Fix: pass a UTF-8 text file.") from err
        meta, body = split_front_matter(raw)
    else:
        body = text
    body = body.strip()
    if not body:
        raise HarnessError(
            "memory promote: the fact is empty. Fix: give a fact with text.")

    words = body.split()
    title = (_one_line(meta.get("name") or "")
             or (source.stem if source is not None else " ".join(words[:8])))
    summary = _one_line(meta.get("description") or "") or _first_line(body)
    slug = slugify(name or meta.get("name")
                   or (source.stem if source is not None
                       else " ".join(words[:6])))
    if f"{slug}.md".casefold() == INDEX_NAME.casefold():
        raise HarnessError(
            f"memory promote: the name {slug!r} is the index file. "
            f"Fix: pass --name <new-name>.")
    identity = git_identity(root)          # before any write
    rel = f"{SHARED_DIR}/{slug}.md"
    target = root / rel
    shared = root / SHARED_DIR
    if (target.is_symlink() or shared.is_symlink()
            or target.resolve().parent != shared.resolve()):
        raise HarnessError(
            f"memory promote: {rel} is a link or leaves the shared folder. "
            f"Fix: remove the link or pass --name <new-name>.")
    line = index_line(title, slug, summary)

    if target.exists():
        _old, old_body = split_front_matter(target.read_text(encoding="utf-8"))
        if old_body.strip() != body:
            raise HarnessError(
                f"memory promote: {rel} exists with other text. "
                f"Fix: pass --name <new-name>.")
        return {"promoted": False, "reason": "already shared", "path": rel,
                "index_line_added": _add_index_line(root, line, slug)}

    front = {k: v for k, v in meta.items()
             if k not in ("name", "description", "promoted_by", "promoted_at")}
    front = {"name": title, "description": summary, **front,
             "promoted_by": identity, "promoted_at": now_iso()}
    target.parent.mkdir(parents=True, exist_ok=True)
    ensure_index(root)
    _write_atomic(target, _render_fact(front, body))
    _add_index_line(root, line, slug)
    return {"promoted": True, "path": rel, "promoted_by": identity,
            "promoted_at": front["promoted_at"], "index_line": line,
            "entries": len(index_entries(root))}


# ------------------------------------------------------- personal memory
def main_repo_root(root) -> Path:
    """The main worktree's root. Linked worktrees share one personal memory."""
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--path-format=absolute",
         "--git-common-dir"], capture_output=True, text=True)
    if proc.returncode == 0 and proc.stdout.strip():
        common = Path(proc.stdout.strip())
        if common.name == ".git":
            return common.parent.resolve()
    return Path(root).resolve()


def project_slug(path) -> str:
    """Claude Code's project folder name for a path.

    Derivation: replace every character that is not `A-Z`, `a-z` or `0-9`
    with `-`. Example: `/Users/me/my.app` -> `-Users-me-my-app`. Source:
    Claude Code names `~/.claude/projects/<slug>/` this way (observed
    behavior of Claude Code auto memory, not a documented API), and it
    keys on the main repository path, so linked worktrees share one folder.
    """
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def _setting(path: Path, key: str):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get(key) if isinstance(data, dict) else None
    return value if isinstance(value, str) and value.strip() else None


def personal_memory_dir(root) -> Path:
    """Where Claude Code keeps this project's personal (auto) memory.

    1. `autoMemoryDirectory` in `.claude/settings.local.json`, then in the
       user settings (`$CLAUDE_CONFIG_DIR` or `~/.claude`)/settings.json.
       Project `.claude/settings.json` is not read: Claude Code does not
       accept the key there. The value must be an absolute path or start
       with `~/`. Claude Code does not support relative paths, so harness
       ignores a relative value rather than guess a base directory.
    2. Else `<config dir>/projects/<slug>/memory`, where the slug comes
       from `project_slug(main_repo_root(root))`.
    """
    root = Path(root)
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR")
                      or Path.home() / ".claude")
    for settings in (root / ".claude" / "settings.local.json",
                     config_dir / "settings.json"):
        value = _setting(settings, "autoMemoryDirectory")
        if value:
            path = Path(os.path.expanduser(value))
            if path.is_absolute():
                return path
    return config_dir / "projects" / project_slug(main_repo_root(root)) / "memory"


def changed_since(directory, since: float) -> list:
    """Memory files (`*.md`, not the index) modified at or after `since`."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return sorted(str(p) for p in directory.rglob("*.md")
                  if p.is_file() and p.name != INDEX_NAME
                  and p.stat().st_mtime >= since)


def slice_started_epoch(root, slice_id: str) -> int:
    """Commit time of the slice's `started_at_commit`: a lower bound on the
    slice start, so the changed-file list never misses a file."""
    base = get_slice(root, slice_id).get("started_at_commit")
    if not base:
        raise HarnessError(
            f"memory changed: slice {slice_id} has no started_at_commit. "
            f"Fix: pass --since <ISO time>.")
    proc = subprocess.run(["git", "-C", str(root), "show", "-s",
                           "--format=%ct", base], capture_output=True, text=True)
    out = proc.stdout.strip()
    if proc.returncode != 0 or not out.isdigit():
        raise HarnessError(
            f"memory changed: commit {base[:12]} not found. "
            f"Fix: pass --since <ISO time>.")
    return int(out)


# ------------------------------------------------------------- CLAUDE.md
def claude_md_state(root) -> str:
    """`missing`, `current` (has the import), `marked` (harness file without
    the import) or `unmarked` (someone else's file without the import)."""
    path = Path(root) / "CLAUDE.md"
    if not path.exists():
        return "missing"
    text = path.read_text(encoding="utf-8")
    if any(line.strip() == CLAUDE_IMPORT for line in text.splitlines()):
        return "current"
    return "marked" if _MARKER_LINE.search(text) else "unmarked"


def add_claude_import(root) -> bool:
    """Append the import to a harness-marked CLAUDE.md. True when written."""
    if claude_md_state(root) != "marked":
        return False
    path = Path(root) / "CLAUDE.md"
    text = path.read_text(encoding="utf-8").rstrip("\n")
    path.write_text(f"{text}\n{CLAUDE_IMPORT}\n", encoding="utf-8")
    return True
