"""0.10 removed working and durable memory (D-0.10-02). Nothing that ships
may write or read it. `engine/upgrade_w3.py` migrates old repos, so it is
the one allowed reference."""
import re

from conftest import PLUGIN_ROOT

FORBIDDEN = re.compile(
    r"memory (?:write|flush|compact)\b"
    r"|[\"']memory[\"'],\s*[\"'](?:write|flush|compact)[\"']"
    r"|\.harness/memory|memory/session|durable\.jsonl"
    r"|durable[ _]memor|session memory|attempt memory"
    r"|compact_to_durable|from engine import memory|from \. import memory")
SCANNED = ("bin", "engine", "hooks", "adapters", "skills", "agents",
           "templates")
SUFFIXES = {".py", ".js", ".ts", ".json", ".toml", ".md", ".yml", ".yaml",
            ".sh", ""}
ALLOWED = {"engine/upgrade_w3.py"}


def _shipped_files():
    for top in SCANNED:
        base = PLUGIN_ROOT / top
        for path in ([base] if base.is_file() else sorted(base.rglob("*"))):
            rel = path.relative_to(PLUGIN_ROOT).as_posix()
            if (path.is_dir() or "__pycache__" in path.parts
                    or rel in ALLOWED or path.suffix not in SUFFIXES):
                continue
            yield rel, path


def test_no_shipped_file_uses_durable_memory():
    hits = []
    for rel, path in _shipped_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            if FORBIDDEN.search(line):
                hits.append(f"{rel}:{n}: {line.strip()}")
    assert not hits, "durable memory is gone in 0.10:\n" + "\n".join(hits)


def test_engine_memory_module_is_gone():
    assert not (PLUGIN_ROOT / "engine" / "memory.py").exists()


def test_close_journal_lives_in_the_ignored_cache(toy):
    from conftest import git
    from engine.cli.closure_state import journal_path
    path = journal_path(toy, "slice-042")
    assert path.parent == toy / ".harness" / "cache"
    assert path.name.startswith("close-")
    rel = path.relative_to(toy).as_posix()
    assert git(toy, "check-ignore", "-q", rel).returncode == 0
