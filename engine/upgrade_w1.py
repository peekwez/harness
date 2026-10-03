"""Harness 0.10 upgrade steps owned by W1: shadows and context (spec §12
steps 1, 5 and 8). Each step is idempotent: after `apply`, `describe`
returns []."""
from __future__ import annotations

import copy
import re
import shutil
import subprocess
from pathlib import Path

from . import HarnessError, harness_dir, read_jsonl, write_jsonl
from .upgrade_010 import SKIPPED, Ask, Step, register

SHADOWS_DIR = ".harness/shadows"
SHADOWS_ATTRIBUTE = ".harness/shadows/** merge=ours"
CACHE_IGNORE = ".harness/cache/"
RESOLVER_KEYS = ("budget_tokens", "ranking", "degrade")


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)


def _lines(path: Path) -> list:
    return path.read_text().splitlines() if path.exists() else []


# ------------------------------------------------------------ .gitignore
def _describe_cache_ignore(root: Path) -> list:
    present = {line.strip() for line in _lines(root / ".gitignore")}
    if present & {CACHE_IGNORE, CACHE_IGNORE.rstrip("/")}:
        return []
    return [f"add {CACHE_IGNORE} to .gitignore"]


def _apply_cache_ignore(root: Path, ask: Ask) -> list:
    lines = _lines(root / ".gitignore")
    lines.append(CACHE_IGNORE)
    (root / ".gitignore").write_text("\n".join(lines) + "\n")
    return [f"added {CACHE_IGNORE} to .gitignore"]


# ------------------------------------------------------------ shadows
def _tracked_shadows(root: Path) -> list:
    proc = _git(root, "ls-files", "--", SHADOWS_DIR)
    return [p for p in proc.stdout.splitlines() if p] if proc.returncode == 0 else []


def _describe_shadows(root: Path) -> list:
    changes = []
    tracked = _tracked_shadows(root)
    if tracked:
        changes.append(f"untrack {len(tracked)} files under {SHADOWS_DIR}/")
    if (root / SHADOWS_DIR).exists():
        changes.append(f"delete {SHADOWS_DIR}/; shadows now live in "
                       f".harness/cache/shadows/")
    if SHADOWS_ATTRIBUTE in _lines(root / ".gitattributes"):
        changes.append(f"remove '{SHADOWS_ATTRIBUTE}' from .gitattributes")
    return changes


def _apply_shadows(root: Path, ask: Ask) -> list:
    if not ask(f"Delete {SHADOWS_DIR}/? Harness 0.10 rebuilds shadows in the "
               f"gitignored .harness/cache/shadows/."):
        return [SKIPPED]
    report = []
    tracked = _tracked_shadows(root)
    if tracked:
        proc = _git(root, "rm", "-r", "-q", "--cached", "--ignore-unmatch",
                    "--", SHADOWS_DIR)
        if proc.returncode != 0:
            raise HarnessError(
                f"w1.untrack-shadows: git rm --cached {SHADOWS_DIR} failed: "
                f"{proc.stderr.strip()}. Fix the index, then run: harness upgrade")
        report.append(f"untracked {len(tracked)} files under {SHADOWS_DIR}/")
    if (root / SHADOWS_DIR).exists():
        shutil.rmtree(root / SHADOWS_DIR)
        report.append(f"deleted {SHADOWS_DIR}/")
    lines = _lines(root / ".gitattributes")
    if SHADOWS_ATTRIBUTE in lines:
        kept = [line for line in lines if line != SHADOWS_ATTRIBUTE]
        (root / ".gitattributes").write_text(
            "\n".join(kept) + "\n" if kept else "")
        report.append(f"removed '{SHADOWS_ATTRIBUTE}' from .gitattributes")
    return report


# ------------------------------------------------------------ registry
def _registry(root: Path) -> tuple:
    path = harness_dir(root) / "registry.jsonl"
    return path, (read_jsonl(path) if path.exists() else [])


def _describe_registry(root: Path) -> list:
    _path, rows = _registry(root)
    n = sum(1 for r in rows if isinstance(r, dict) and "shadow" in r)
    return [f"remove the shadow field from {n} registry rows"] if n else []


def _apply_registry(root: Path, ask: Ask) -> list:
    path, rows = _registry(root)
    n = 0
    for r in rows:
        if isinstance(r, dict) and "shadow" in r:
            r.pop("shadow")
            n += 1
    write_jsonl(path, rows)
    return [f"removed the shadow field from {n} registry rows"]


# ------------------------------------------------------------ config.yaml
def _config_path(root: Path) -> Path:
    return harness_dir(root) / "config.yaml"


def _load_yaml(text: str):
    import yaml
    try:
        return yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise HarnessError(
            f"w1.drop-resolver-config: .harness/config.yaml is not valid YAML: "
            f"{exc}. Fix it, then run: harness upgrade") from exc


def _resolver_keys_in(data) -> list:
    resolver = data.get("resolver") if isinstance(data, dict) else None
    if not isinstance(resolver, dict):
        return []
    return [k for k in RESOLVER_KEYS if k in resolver]


def _strip_resolver_keys(text: str) -> str:
    """Remove resolver.budget_tokens / ranking / degrade lines. Comments and
    every other key stay; the `resolver:` line goes when nothing is left."""
    lines = text.splitlines(keepends=True)
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if not re.match(r"^resolver:\s*(#.*)?$", line.rstrip("\r\n")):
            out.append(line)
            i += 1
            continue
        j, block = i + 1, []
        while j < len(lines) and (not lines[j].strip()
                                  or lines[j][:1] in (" ", "\t")):
            block.append(lines[j])
            j += 1
        kept, skip_indent = [], None
        for child in block:
            indent = len(child) - len(child.lstrip())
            if (skip_indent is not None and child.strip()
                    and (indent > skip_indent
                         or (indent == skip_indent
                             and child.lstrip().startswith("-")))):
                continue                     # continuation of a removed key
            skip_indent = None
            m = re.match(r"^(\s+)([A-Za-z_][A-Za-z0-9_]*)\s*:", child)
            if m and m.group(2) in RESOLVER_KEYS:
                skip_indent = len(m.group(1))
                continue
            kept.append(child)
        if any(c.strip() and not c.lstrip().startswith("#") for c in kept):
            out.append(line)
            out.extend(kept)
        else:
            out.extend(c for c in kept if not c.strip())
        i = j
    return "".join(out)


def _describe_resolver(root: Path) -> list:
    path = _config_path(root)
    if not path.exists():
        return []
    keys = _resolver_keys_in(_load_yaml(path.read_text()))
    return [f"remove resolver.{k} from .harness/config.yaml" for k in keys]


def _apply_resolver(root: Path, ask: Ask) -> list:
    import yaml
    path = _config_path(root)
    before = _resolver_keys_in(_load_yaml(path.read_text()))
    original = _load_yaml(path.read_text())
    text = _strip_resolver_keys(path.read_text())
    data = _load_yaml(text)
    expected = copy.deepcopy(original)
    if isinstance(expected.get("resolver"), dict):
        for key in RESOLVER_KEYS:
            expected["resolver"].pop(key, None)
        if not expected["resolver"]:
            expected.pop("resolver")
    if data != expected:
        data = expected
        text = None
    if text is None or _resolver_keys_in(data):
        # flow style or an unusual layout: rewrite through YAML (comments go)
        text = yaml.safe_dump(data, sort_keys=False)
    path.write_text(text)
    return [f"removed resolver.{k} from .harness/config.yaml" for k in before]


register(Step(
    id="w1.gitignore-cache",
    title="Add .harness/cache/ to .gitignore.",
    describe=_describe_cache_ignore, apply=_apply_cache_ignore))
register(Step(
    id="w1.untrack-shadows",
    title="Untrack and delete .harness/shadows/. Shadows now live in the "
          "gitignored cache.",
    describe=_describe_shadows, apply=_apply_shadows, destructive=True))
register(Step(
    id="w1.drop-registry-shadow",
    title="Remove the shadow field from registry rows.",
    describe=_describe_registry, apply=_apply_registry))
register(Step(
    id="w1.drop-resolver-config",
    title="Remove resolver.budget_tokens, ranking and degrade from config.yaml.",
    describe=_describe_resolver, apply=_apply_resolver))
