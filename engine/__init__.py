"""harness engine — framework-agnostic enforcement core.

One substrate: all project state is git-tracked JSONL/markdown plus one
gitignored SQLite sidecar. The engine is stateless per invocation.
Fail closed, fail loud: missing required artifacts are hard errors.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import time
from pathlib import Path

SCHEMA_VERSION = 1
ENGINE_VERSION = "0.7.1"

# Extensions we consider "source modules". Anything else in these families is
# either substrate/docs (ignored) or unknown-language source (degenerate
# shadow + G8 finding — never a silent hole).
IGNORED_EXTS = {
    ".md", ".txt", ".json", ".jsonl", ".toml", ".cfg", ".ini", ".lock",
    ".csv", ".html", ".css", ".svg", ".png", ".jpg", ".gif", ".pdf",
    ".scm", ".db", ".gitignore", ".yml_disabled", ".sample",
}
IGNORED_DIRS = {".git", ".harness", "node_modules", "__pycache__", ".venv",
                "venv", ".pytest_cache", ".claude-plugin", ".worktrees"}


class HarnessError(Exception):
    """Engine error (nonzero exit). Verdicts carry semantics; this does not."""


class SubstrateMissing(HarnessError):
    pass


class SchemaError(HarnessError):
    pass


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def token_estimate(text: str) -> int:
    """Deterministic token estimate: ~4 chars/token."""
    return max(1, (len(text) + 3) // 4)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())


def find_root(start=None) -> Path:
    """Walk up from start until a .harness/ substrate is found. Fail loud."""
    p = Path(start or os.getcwd()).resolve()
    for cand in (p, *p.parents):
        if (cand / ".harness").is_dir():
            return cand
    raise SubstrateMissing(
        f"no .harness substrate found walking up from {p}; run `harness init` first"
    )


def harness_dir(root) -> Path:
    return Path(root) / ".harness"


def check_schema_version(root) -> None:
    sv = harness_dir(root) / "schema_version"
    if not sv.exists():
        raise SchemaError(f"{sv} missing — substrate not initialised (fail closed)")
    found = sv.read_text().strip()
    if found != str(SCHEMA_VERSION):
        raise SchemaError(
            f"substrate schema_version={found}, engine expects {SCHEMA_VERSION}; "
            f"run `harness init --migrate`"
        )


def read_jsonl(path) -> list:
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise HarnessError(f"{path}:{lineno}: invalid JSONL: {exc}") from exc
    return rows


def append_jsonl(path, obj: dict) -> None:
    """Single-write append; O_APPEND single-line writes are concurrency-safe."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, sort_keys=True, ensure_ascii=False) + "\n"
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def write_jsonl(path, rows: list) -> None:
    """Atomic whole-file rewrite: serialize first, write to a temp file in
    the same directory, then os.replace. A crash (or a concurrent reader)
    never sees a truncated substrate file — the system's entire value is
    substrate integrity."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n"
                   for r in rows)          # raises BEFORE anything is touched
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


# ---------------------------------------------------------------- substrate accessors
def load_backlog(root) -> list:
    path = harness_dir(root) / "backlog.jsonl"
    if not path.exists():
        raise SubstrateMissing(f"{path} missing — run /harness:backlog (fail closed)")
    return read_jsonl(path)


def get_slice(root, slice_id: str) -> dict:
    for s in load_backlog(root):
        if s.get("id") == slice_id:
            return s
    raise SubstrateMissing(f"slice {slice_id!r} not found in backlog.jsonl (fail closed)")


def save_slice(root, row: dict) -> None:
    rows = load_backlog(root)
    for i, s in enumerate(rows):
        if s.get("id") == row.get("id"):
            rows[i] = row
            break
    else:
        rows.append(row)
    write_jsonl(harness_dir(root) / "backlog.jsonl", rows)


def load_decisions(root) -> list:
    path = harness_dir(root) / "decisions.jsonl"
    if not path.exists():
        raise SubstrateMissing(f"{path} missing — substrate incomplete (fail closed)")
    return read_jsonl(path)


def load_boundaries(root) -> list:
    """G3 scope boundaries compiled from [non-goal] blocks. Optional."""
    return read_jsonl(harness_dir(root) / "boundaries.jsonl")


# Source roots stripped from a source path to make a module id (ADR-002 /
# D-008): `packages/kente-config/src/kente/config/__init__.py` -> the module
# id `kente.config`. A repo matching none of these keeps the dotted relative
# path it always had.
DEFAULT_SRC_ROOTS = ["src", "packages/*/src"]

DEFAULT_CONFIG = {
    "schema": 1,
    "resolver": {
        "budget_tokens": 8000,
        "ranking": ["direct_deps", "one_hop_types", "durable_memories"],
        "degrade": "drop_docstrings_before_modules",
    },
    "gates": {
        "g3_mode": "allow_with_findings",       # or: block | radius
        "g5_override": "recorded_justification",  # or: advisory | park
        "g5_similarity_threshold": 0.6,
        "acceptance_runner": "pytest",          # or: none (skill-enforced only)
        "acceptance_python": None,              # default: .venv/bin/python if present
    },
    "ensemble": {"trigger_confidence_below": 0.7, "samples": 3},
    "review": {"fork_for_security_rows": True},   # ADR-001
    "extractor": {"src_roots": list(DEFAULT_SRC_ROOTS)},
    "languages": {"python": True, "typescript": True, "rust": True,
                  "go": True, "yaml": True, "hcl": True},
    "telemetry": {"compaction_is_defect": True},
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(root) -> dict:
    cfg_path = harness_dir(root) / "config.yaml"
    if not cfg_path.exists():
        raise SubstrateMissing(f"{cfg_path} missing — substrate incomplete (fail closed)")
    try:
        import yaml  # engine dependency, declared in pyproject
        loaded = yaml.safe_load(cfg_path.read_text()) or {}
    except ImportError as exc:
        raise HarnessError("PyYAML required: pip install pyyaml") from exc
    if not isinstance(loaded, dict):
        raise SchemaError(f"{cfg_path}: expected a mapping")
    # deep-copied: nested defaults the repo does not override would
    # otherwise be shared with DEFAULT_CONFIG, and one caller mutating
    # `config["extractor"]["src_roots"]` would move every module id in the
    # process (fail loud, never quietly global)
    return _deep_merge(copy.deepcopy(DEFAULT_CONFIG), loaded)
