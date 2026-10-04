"""Always-on context cost (spec §7.5): what every session pays up front.

Each source is reported in characters and estimated tokens (4 characters
per token, the estimate `engine.token_estimate` uses)."""
from __future__ import annotations

from pathlib import Path

from .shared_memory import INDEX_REL

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def _tokens(chars: int) -> int:
    return (chars + 3) // 4


def _frontmatter(text: str) -> dict:
    """Top-level `key: value` lines between the leading `---` markers."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, sep, value = line.partition(":")
        if sep and not line.startswith((" ", "\t")):
            out[key.strip()] = value.strip().strip('"')
    return out


def listing_chars(directory: Path, pattern: str) -> int:
    """Characters a host spends listing skills or agents: `name: description`
    per file, the text every session loads."""
    total = 0
    for path in sorted(Path(directory).glob(pattern)):
        fm = _frontmatter(path.read_text(encoding="utf-8"))
        if fm.get("name") or fm.get("description"):
            total += len(f"{fm.get('name', '')}: {fm.get('description', '')}")
    return total


def _file_chars(path: Path) -> int:
    return len(path.read_text(encoding="utf-8")) if path.is_file() else 0


def always_on_cost(root, plugin_root=None) -> dict:
    """Per-source always-on cost and the total.

    Args:
        root: Repo root (AGENTS.md, shared memory index, sidecar).
        plugin_root: Plugin install holding `skills/` and `agents/`;
            default: the tree this engine runs from.
    """
    from .events import Sidecar
    root = Path(root)
    plugin_root = Path(plugin_root or PLUGIN_ROOT)
    sidecar = Sidecar(root)
    try:
        last = int(sidecar.state_get("__context__", "last_injection_chars", 0) or 0)
    finally:
        sidecar.close()
    chars = {
        "skills": listing_chars(plugin_root / "skills", "*/SKILL.md"),
        "agents": listing_chars(plugin_root / "agents", "*.md"),
        "agents_md": _file_chars(root / "AGENTS.md"),
        "shared_memory": _file_chars(root / INDEX_REL),
        "last_injection": last,
    }
    total = sum(chars.values())
    return {"sources": {k: {"chars": v, "tokens": _tokens(v)}
                        for k, v in chars.items()},
            "total": {"chars": total, "tokens": _tokens(total)}}
