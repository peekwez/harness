"""Shared fixtures: a toy repo with a real substrate, per §6 acceptance."""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # `from conftest import …`

HARNESS_BIN = PLUGIN_ROOT / "bin" / "harness"

from engine import write_jsonl  # noqa: E402


def run_cli(*args, root=None, stdin=None, env=None):
    import os
    e = dict(os.environ)
    if env:
        e.update(env)
    cmd = [sys.executable, str(HARNESS_BIN)]
    if root:
        cmd += ["--root", str(root)]
    cmd += [str(a) for a in args]
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True, env=e)


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)


TELEMETRY_PY = '''"""Telemetry module."""

__all__ = ["emit_span"]


def emit_span(name: str, attrs: dict) -> dict:
    """Emit a span with the given name and attributes."""
    return {"name": name, "attrs": attrs}
'''

CONFIG_PY = '''"""Config module."""


def get_config(key: str, default=None):
    """Look up a typed config value."""
    return default
'''

ORDERS_PY = '''"""Orders service."""
import telemetry


def create_order(sku: str) -> dict:
    """Create an order and emit a span."""
    telemetry.emit_span("create_order", {"sku": sku})
    return {"sku": sku}
'''

ADR_007 = '''---
id: "007"
status: accepted
domains: [telemetry]
supersedes: []
decision_table_rows:
  - id: D-041
    domain: telemetry
    question: "Span naming convention?"
    answer: "snake_case verb_noun; never free-form strings."
abstractions:
  - id: telemetry
    kind: telemetry
    source: telemetry.py
    section: s2
api_surface: []
---

# ADR-007: Telemetry

## Status

Accepted.

## Context

<!-- #s1 -->
Telemetry section one: general context prose.

<!-- #s2 -->
Use emit_span for all instrumentation. SUPERSEDABLE-GUIDANCE-MARKER.

<!-- #s3 -->
Never log PII into span attributes. SURVIVING-GUIDANCE-MARKER.

## Decision

emit_span is the single entry point.

## Consequences

Spans everywhere.

## Considered Alternatives

Bare logging.

## Implementation

[non-goal] Rewriting the legacy exporter under `legacy/**` is out of scope.
'''


def make_config(budget=8000, g3_mode="allow_with_findings",
                g5_override="recorded_justification"):
    return textwrap.dedent(f"""\
        schema: 1
        resolver:
          budget_tokens: {budget}
          ranking: [direct_deps, one_hop_types, durable_memories]
          degrade: drop_docstrings_before_modules
        gates:
          g3_mode: {g3_mode}
          g5_override: {g5_override}
          g5_similarity_threshold: 0.6
        ensemble:
          trigger_confidence_below: 0.7
          samples: 3
        languages:
          python: true
          typescript: true
          yaml: true
          hcl: true
        telemetry:
          compaction_is_defect: true
        """)


def build_toy_repo(root: Path, budget=8000, **cfg_kw) -> Path:
    """Substrate + two modules (telemetry built, config planned) + slice-042."""
    hdir = root / ".harness"
    (hdir / "memory" / "session").mkdir(parents=True)
    (hdir / "shadows").mkdir()
    (hdir / "config.yaml").write_text(make_config(budget=budget, **cfg_kw))
    (hdir / "schema_version").write_text("1\n")
    for empty in ("edges.jsonl", "telemetry.jsonl", "memory/durable.jsonl"):
        (hdir / empty).touch()

    (root / "telemetry.py").write_text(TELEMETRY_PY)
    (root / "config.py").write_text(CONFIG_PY)
    (root / "adr").mkdir()
    (root / "adr" / "007-telemetry.md").write_text(ADR_007)
    (root / "contracts").mkdir()
    (root / "contracts" / "api.yaml").write_text(
        "openapi: 3.0.3\ninfo: {title: api, version: 0.1.0}\n"
        "paths:\n  /health:\n    get:\n      responses:\n        '200':\n"
        "          description: ok\n")
    tests_dir = root / "tests" / "slices"
    tests_dir.mkdir(parents=True)
    (tests_dir / "042_orders.py").write_text(
        "def test_orders():\n    import orders\n    assert orders.create_order('x')\n")

    registry = [
        {"id": "telemetry", "kind": "telemetry", "status": "planned",
         "module_id": None, "source": "telemetry.py", "source_hash": None,
         "shadow": None,
         "guidance_refs": ["adr/007-telemetry.md#s2", "adr/007-telemetry.md#s3"],
         "supersedes_guidance": ["adr/007#s2"],
         "manifest": ["telemetry.py"], "signature_digest": None},
        {"id": "config", "kind": "config", "status": "planned",
         "module_id": None, "source": "config.py", "source_hash": None,
         "shadow": None, "guidance_refs": ["adr/007-telemetry.md#s1"],
         "supersedes_guidance": [], "manifest": ["config.py"],
         "signature_digest": None},
        {"id": "orders", "kind": "component", "status": "planned",
         "module_id": None, "source": "orders.py", "source_hash": None,
         "shadow": None, "guidance_refs": [], "supersedes_guidance": [],
         "manifest": [], "signature_digest": None},
    ]
    write_jsonl(hdir / "registry.jsonl", registry)
    write_jsonl(hdir / "decisions.jsonl", [
        {"id": "D-041", "domain": "telemetry",
         "question": "Span naming convention?",
         "answer": "snake_case verb_noun; never free-form strings.",
         "adr_ref": "adr/007-telemetry.md", "origin": "phase0",
         "created": "2026-01-01T00:00:00+00:00"},
    ])
    write_jsonl(hdir / "backlog.jsonl", [
        {"id": "slice-042", "spec": "spec-007", "title": "orders service",
         "status": "planned", "declares_dep": ["telemetry", "config"],
         "acceptance": ["tests/slices/042_orders.py"],
         "predicted_files": ["orders.py"],
         "context_cost_estimate": 0, "depends_on": [], "worktree": None},
    ])
    write_jsonl(hdir / "boundaries.jsonl", [
        {"id": "B-legacy", "source_adr": "007", "rule_ref": "adr:007",
         "text": "legacy exporter out of scope", "patterns": ["legacy/**"]},
    ])

    # build telemetry: extract shadow + flip status
    from engine import load_config
    from engine.extractor.engine import extract_path
    from engine.registry import flip_status
    config = load_config(root)
    extract_path(root, root / "telemetry.py", config)
    extract_path(root, root / "config.py", config)
    flip_status(root, "telemetry")

    (root / ".gitattributes").write_text(
        ".harness/telemetry.jsonl merge=union\n"
        ".harness/edges.jsonl merge=union\n"
        ".harness/memory/durable.jsonl merge=union\n"
        ".harness/backlog.jsonl merge=harness-substrate\n"
        ".harness/registry.jsonl merge=harness-substrate\n"
        ".harness/decisions.jsonl merge=harness-substrate\n"
        ".harness/shadows/** merge=ours\n")
    (root / ".gitignore").write_text(
        ".harness/sidecar.db\n.harness/sidecar.db-*\n"
        ".harness/memory/session/\n.worktrees/\n"
        ".claude/settings.local.json\n"
        "__pycache__/\n*.pyc\n.pytest_cache/\n")
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@t")
    git(root, "config", "user.name", "t")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "toy repo baseline")
    return root


@pytest.fixture
def toy(tmp_path):
    return build_toy_repo(tmp_path / "toy")


@pytest.fixture
def plugin_root():
    return PLUGIN_ROOT


def make_event(event, session="s1", slice_id="slice-042", files=None,
               context=None, prompt=None):
    return {"event": event, "session_id": session, "work_unit_id": slice_id,
            "payload": {"files": [{"path": f, "proposed_content_hash": None}
                                  for f in (files or [])],
                        "context_loaded": context or [],
                        "diff": None, "prompt": prompt}}


def loaded_context(root, session="s1", slice_id="slice-042"):
    """Run Phase 1 (session_start) so the session has its context."""
    from engine.events import handle_event
    return handle_event(make_event("session_start", session=session,
                                   slice_id=slice_id), root)
