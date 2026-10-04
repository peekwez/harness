"""W8 upgrade steps: refresh a harness-written AGENTS.md, then drop stale rules.

0.8 and 0.9 wrote `.gitattributes` merge rules for shadows, telemetry and
durable memory, and a `.gitignore` line for session memory. 0.10 removes
those files. A rule stays while its file exists (a declined step keeps the
file) and while the engine still writes it.
"""
from __future__ import annotations

from pathlib import Path

from .upgrade_010 import SKIPPED, Step, keep_backup, register, write_lines

# merge path -> the file or folder whose absence makes the rule stale
LEGACY_MERGE_PATHS = {
    ".harness/shadows/**": ".harness/shadows",
    ".harness/telemetry.jsonl": ".harness/telemetry.jsonl",
    ".harness/telemetry.archive.jsonl": ".harness/telemetry.archive.jsonl",
    ".harness/memory/durable.jsonl": ".harness/memory",
}
LEGACY_IGNORES = {".harness/memory/session/": ".harness/memory"}

# ------------------------------------------------------------ AGENTS.md
LEGACY_HEADING = "# AGENTS.md — this repo is harness-enforced"
MARKER_010 = "<!-- harness:agents-md 0.10 -->"
BACKUP_REL = ".harness/cache/AGENTS.md.pre-0.10"


def _agents_template() -> str:
    from .cli.common import PLUGIN_ROOT
    return (PLUGIN_ROOT / "templates" / "agents-md.md").read_text()


def agents_md_state(root) -> str:
    """missing | legacy | current | custom. The 0.10 marker wins: the
    template's first line is the legacy heading."""
    path = Path(root) / "AGENTS.md"
    if not path.exists():
        return "missing"
    text = path.read_text()
    if MARKER_010 in text:
        return "current"
    if text.splitlines()[:1] == [LEGACY_HEADING]:
        return "legacy"
    return "custom"


def agents_md_describe(root) -> list:
    if agents_md_state(root) == "legacy":
        return [f"replace the 0.9 AGENTS.md with the 0.10 template (backup: {BACKUP_REL})"]
    return []


def agents_md_apply(root, ask) -> list:
    root = Path(root)
    if agents_md_state(root) != "legacy":
        return []
    if not ask(f"Replace AGENTS.md with the 0.10 template? The old file is kept at {BACKUP_REL}."):
        return [SKIPPED]
    path = root / "AGENTS.md"
    # w2.skill-names ran first, so the backup already has renamed skills.
    # An earlier run's backup is never overwritten.
    backup = keep_backup(root, "AGENTS.md", path.read_bytes())
    path.write_text(_agents_template())
    return [f"replaced AGENTS.md. Backup at {backup}, after the skill renames."]


def agents_md_advise(root) -> list:
    root = Path(root)
    if agents_md_state(root) == "custom":
        return ["check: AGENTS.md is not harness-written. Compare it with the "
                "harness template and add the 0.10 rules by hand."]
    return [f"check: compare the gitignored backup {rel} (after the skill renames) "
            "with AGENTS.md and carry over local edits. Then delete the backup."
            for rel in _agents_backups(root)]


def _agents_backups(root: Path) -> list:
    """BACKUP_REL, then the numbered backups of later runs."""
    cache = root / ".harness" / "cache"
    found = [p.relative_to(root).as_posix() for p in cache.glob("AGENTS.md.pre-0.10*")
             if p.name == "AGENTS.md.pre-0.10" or p.suffix[1:].isdigit()]
    return sorted(found, key=lambda rel: (len(rel), rel))


AGENTS_STEP = register(Step(
    id="w8.agents-md",
    title="Replace a harness-written AGENTS.md with the 0.10 template.",
    describe=agents_md_describe, apply=agents_md_apply, destructive=True,
    advise=agents_md_advise))


# ------------------------------------------------------------ merge rules
def _current_merge_paths() -> set:
    from .cli import common
    names = ("SUBSTRATE_UNION_MERGE", "SUBSTRATE_KEYED_MERGE", "SUBSTRATE_OURS_MERGE")
    return {p for name in names for p in getattr(common, name, ())}


def _stale_attribute_lines(root: Path) -> list:
    path = root / ".gitattributes"
    if not path.exists():
        return []
    keep = _current_merge_paths()
    out = []
    for line in path.read_text().splitlines():
        parts = line.split()
        if (len(parts) == 2 and parts[1].startswith("merge=")
                and parts[0] in LEGACY_MERGE_PATHS and parts[0] not in keep
                and not (root / LEGACY_MERGE_PATHS[parts[0]]).exists()):
            out.append(line)
    return out


def _stale_ignore_lines(root: Path) -> list:
    path = root / ".gitignore"
    if not path.exists():
        return []
    return [line for line in path.read_text().splitlines()
            if line.strip() in LEGACY_IGNORES
            and not (root / LEGACY_IGNORES[line.strip()]).exists()]


def _drop(path: Path, stale: set) -> None:
    write_lines(path, [line for line in path.read_text().splitlines() if line not in stale])


def describe(root) -> list:
    root = Path(root)
    return ([f".gitattributes: remove `{line}`" for line in _stale_attribute_lines(root)]
            + [f".gitignore: remove `{line}`" for line in _stale_ignore_lines(root)])


def apply(root, ask) -> list:
    root = Path(root)
    report = []
    attrs = _stale_attribute_lines(root)
    if attrs:
        _drop(root / ".gitattributes", set(attrs))
        report += [f".gitattributes: removed `{line}`" for line in attrs]
    ignores = _stale_ignore_lines(root)
    if ignores:
        _drop(root / ".gitignore", set(ignores))
        report += [f".gitignore: removed `{line}`" for line in ignores]
    return report


STEP = register(Step(
    id="w8.stale-merge-rules",
    title="Remove merge and ignore rules for files that 0.10 removed.",
    describe=describe, apply=apply))
