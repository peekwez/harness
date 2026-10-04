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
    return subprocess.run(cmd, input=stdin if stdin is not None else "",
                          capture_output=True, text=True, env=e)


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


def make_config(g3_mode="allow_with_findings"):
    return textwrap.dedent(f"""\
        schema: 1
        gates:
          g3_mode: {g3_mode}
          g5_similarity_threshold: 0.6
          exempt_paths: [".harness/", "adr/", ".github/", "tests/", "docs/", ".claude/", "explore/"]
        review:
          ensemble: false
        languages:
          python: true
          typescript: true
          yaml: true
          hcl: true
        """)


def build_toy_repo(root: Path, oversized=False, legacy_verification=True,
                   **cfg_kw) -> Path:
    """Substrate + two modules (telemetry built, config planned) + slice-042."""
    hdir = root / ".harness"
    hdir.mkdir(parents=True)
    (hdir / "config.yaml").write_text(make_config(**cfg_kw))
    (hdir / "schema_version").write_text("2\n")
    for empty in ("edges.jsonl", "slice-metrics.jsonl"):
        (hdir / empty).touch()

    (root / "telemetry.py").write_text(TELEMETRY_PY)
    (root / "config.py").write_text(CONFIG_PY)
    (root / "adr").mkdir()
    (root / "adr" / "007-telemetry.md").write_text(ADR_007)
    tests_dir = root / "tests" / "slices"
    tests_dir.mkdir(parents=True)
    (tests_dir / "042_orders.py").write_text(
        "def test_orders():\n    import orders\n    assert orders.create_order('x')\n")

    registry = [
        {"id": "telemetry", "kind": "telemetry", "status": "planned",
         "module_id": None, "source": "telemetry.py", "source_hash": None,
         "guidance_refs": ["adr/007-telemetry.md#s2", "adr/007-telemetry.md#s3"],
         "supersedes_guidance": ["adr/007#s2"],
         "manifest": ["telemetry.py"], "signature_digest": None},
        {"id": "config", "kind": "config", "status": "planned",
         "module_id": None, "source": "config.py", "source_hash": None,
         "guidance_refs": ["adr/007-telemetry.md#s1"],
         "supersedes_guidance": [], "manifest": ["config.py"],
         "signature_digest": None},
        {"id": "orders", "kind": "component", "status": "planned",
         "module_id": None, "source": "orders.py", "source_hash": None,
         "guidance_refs": [], "supersedes_guidance": [],
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
         "context_cost_estimate": 0, "depends_on": [], "worktree": None,
         **({} if legacy_verification is None
            else {"legacy_verification": legacy_verification}),
         },
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
        ".harness/edges.jsonl merge=union\n"
        ".harness/notes.jsonl merge=union\n"
        ".harness/backlog.jsonl merge=harness-substrate\n"
        ".harness/registry.jsonl merge=harness-substrate\n"
        ".harness/decisions.jsonl merge=harness-substrate\n"
        ".harness/slice-metrics.jsonl merge=harness-substrate\n")
    (root / ".gitignore").write_text(
        ".harness/sidecar.db\n.harness/sidecar.db-*\n"
        ".harness/cache/\n"
        ".worktrees/\n"
        ".claude/settings.local.json\n"
        "__pycache__/\n*.pyc\n.pytest_cache/\n")
    if oversized:
        oversize_slice(root)
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@t")
    git(root, "config", "user.name", "t")
    git(root, "config", "maintenance.auto", "false")
    git(root, "config", "gc.auto", "0")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "toy repo baseline")
    return root


CITE_GATE = '''"""Test helper gate: cites non-goals so G3 blocks them (spec 4.1)."""
GATE = {"id": "TOY-CITES", "rule_ref": "adr:007",
        "preferred": ["unit_complete"], "cites": %r}


def run(ctx):
    return []
'''


def cite_non_goals(root, *rules):
    """Install a `gates.extra` gate whose GATE["cites"] lists `rules`
    (boundary ids or rule refs). In 0.10 G3 blocks only cited non-goals."""
    import yaml
    root = Path(root)
    gates_dir = root / ".harness" / "gates"
    gates_dir.mkdir(parents=True, exist_ok=True)
    (gates_dir / "toy_cites.py").write_text(CITE_GATE % (list(rules),))
    cfg_path = root / ".harness" / "config.yaml"
    doc = yaml.safe_load(cfg_path.read_text()) or {}
    gates = doc.setdefault("gates", {})
    extra = list(gates.get("extra") or [])
    if ".harness/gates/toy_cites.py" not in extra:
        extra.append(".harness/gates/toy_cites.py")
    gates["extra"] = extra
    cfg_path.write_text(yaml.safe_dump(doc, sort_keys=False))


def oversize_slice(root: Path, slice_id: str = "slice-042", n: int = 300) -> None:
    """Grow one slice card past MAX_INJECTION_CHARS with predicted files."""
    from engine import read_jsonl
    path = root / ".harness" / "backlog.jsonl"
    rows = read_jsonl(path)
    for row in rows:
        if row["id"] == slice_id:
            row["predicted_files"] = list(row["predicted_files"]) + [
                f"src/generated/module_{i:03d}_with_a_long_descriptive_name.py"
                for i in range(n)]
    write_jsonl(path, rows)


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


def finding_text(f: dict) -> str:
    """Message, fix and injected detail of one finding, as one string."""
    return "\n".join([f["message"], f.get("fix") or "", *f.get("inject", [])])


# ------------------------------------------------------------------ W8: legacy substrates
LEGACY_DIR = Path(__file__).resolve().parent / "fixtures" / "legacy"
REMOVED_SKILLS = ("status", "shadow-context", "premortem", "review-rubrics",
                  "adjudicate", "decision-tables", "slice-decomposition",
                  "contract-first")
LEGACY_CLAUDE_MD = (
    "# CLAUDE.md\n\n"
    "This repo is harness-enforced. The agent working agreement lives "
    "in AGENTS.md (imported below) — slices, gates, provenance, and "
    "the substrate-first workflow.\n\n"
    "@AGENTS.md\n")
UNMARKED_AGENTS_MD = ("# Agent notes\n\n"
                      "Run `make lint` before you push. Ask before you add a dependency.\n")
UNMARKED_CLAUDE_MD = "# Project notes\n\nPrefer small commits.\n\n@AGENTS.md\n"
LEGACY_GITATTRIBUTES = (
    ".harness/telemetry.jsonl merge=union\n"
    ".harness/edges.jsonl merge=union\n"
    ".harness/notes.jsonl merge=union\n"
    ".harness/memory/durable.jsonl merge=union\n"
    ".harness/backlog.jsonl merge=harness-substrate\n"
    ".harness/registry.jsonl merge=harness-substrate\n"
    ".harness/decisions.jsonl merge=harness-substrate\n"
    ".harness/shadows/** merge=ours\n")
LEGACY_GITIGNORE = (".harness/sidecar.db\n.harness/sidecar.db-*\n"
                    ".harness/memory/session/\n.worktrees/\n"
                    ".claude/settings.local.json\n"
                    "__pycache__/\n*.pyc\n.pytest_cache/\n")
LEGACY_PYTEST_INI = ("# harness: make NNN_*.py acceptance tests collectable by bare\n"
                     "# pytest (the engine passes explicit paths and is unaffected)\n"
                     "[pytest]\npython_files = test_*.py *_test.py [0-9]*_*.py\n")
CONTRACT_STUB = ("openapi: 3.0.3\ninfo: {title: api, version: 0.1.0}\n"
                 "paths:\n  /health:\n    get:\n      responses:\n        '200':\n"
                 "          description: ok\n")
MACHINE_STATE = (".git/", ".harness/cache/", ".harness/sidecar.db")
LEGACY_SIDECAR_DDL = """
CREATE TABLE IF NOT EXISTS session_context(
    session_id TEXT, item TEXT, ts TEXT, UNIQUE(session_id, item));
CREATE TABLE IF NOT EXISTS session_state(
    session_id TEXT, key TEXT, value TEXT, UNIQUE(session_id, key));
CREATE TABLE IF NOT EXISTS slice_snapshot(
    slice_id TEXT, module_id TEXT, symbols TEXT, UNIQUE(slice_id, module_id));
CREATE TABLE IF NOT EXISTS touched(
    session_id TEXT, slice_id TEXT, path TEXT, UNIQUE(session_id, slice_id, path));
CREATE TABLE IF NOT EXISTS telemetry_buffer(
    id INTEGER PRIMARY KEY AUTOINCREMENT, row TEXT);
"""

ASTRA_CONFIG_PY = '''"""Typed settings for astra services."""


def get_setting(key: str, default=None):
    """Return one typed setting."""
    return default
'''
ASTRA_ORDERS_PY = '''"""Order intake."""
from astra_core.config import get_setting


def create_order(sku: str) -> dict:
    """Create one order for a SKU."""
    return {"sku": sku, "currency": get_setting("currency", "CAD")}
'''
ASTRA_INVOICE_PY = '''"""Invoices."""


def total(lines: list) -> float:
    """Sum invoice lines to cents."""
    return round(sum(lines), 2)
'''
ASTRA_PYTEST_INI = ("[pytest]\npythonpath = libs/core/src libs/billing/src\n"
                    "python_files = test_*.py *_test.py [0-9]*_*.py\n")


def _write(root, rel, content):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content)
    return path


def _legacy_config(version, extra=""):
    langs = {"go": False, "hcl": False, "python": True, "rust": False,
             "typescript": False, "yaml": True}
    lines = "\n".join(f"  {k}: {str(v).lower()}" for k, v in sorted(langs.items()))
    text = (LEGACY_DIR / f"harness-{version}.yaml").read_text()
    return text.replace("{{languages}}", lines) + extra


def _legacy_settings(root):
    text = (LEGACY_DIR / "claude-settings-0.9.4.json").read_text()
    return text.replace("{{PROJECT_DIR}}", str(Path(root).resolve()))


def _legacy_shadow(root, rel, exports):
    from engine import sha256_text
    source = (Path(root) / rel).read_text()
    payload = {"exports": sorted(exports), "extractor_version": 4,
               "import_candidates": [],
               "language": "python" if rel.endswith(".py") else "javascript",
               "path": rel, "source_hash": sha256_text(source)}
    shadow = f".harness/shadows/{rel}.json"
    _write(root, shadow, json.dumps(payload, indent=1, sort_keys=True) + "\n")
    return shadow


def _legacy_entry(entry_id, kind, status, source=None, text=None, shadow=None):
    from engine import sha256_text
    return {"id": entry_id, "kind": kind, "status": status, "module_id": None,
            "source": source,
            "source_hash": sha256_text(text) if status == "built" else None,
            "shadow": shadow, "guidance_refs": [], "supersedes_guidance": [],
            "manifest": [source] if source else [], "signature_digest": None}


def legacy_events(slice_id, day, count):
    """0.9 telemetry `event` rows for one slice on one day of September."""
    return [{"id": f"evt:{slice_id}-{day}-{i}",
             "ts": f"2026-09-{day:02d}T10:{i:02d}:00+00:00", "kind": "event",
             "meta": {"codes": ["OUT_OF_SCOPE"] if i % 2 else [],
                      "event": "pre_change", "gates": ["G2", "G3"],
                      "session": f"s-{day}", "slice": slice_id,
                      "verdict": "allow_with_findings" if i % 2 else "allow"}}
            for i in range(count)]


def _closed_event(slice_id, day):
    return {"id": f"evt:{slice_id}-closed", "ts": f"2026-09-{day:02d}T11:00:00+00:00",
            "kind": "slice_closed", "meta": {"slice": slice_id}}


def _legacy_edge(etype, frm, to, meta=None):
    return {"ts": "2026-09-01T00:00:00+00:00", "type": etype, "from": frm,
            "to": to, "commit": None, "meta": meta or {}}


def _durable(mem_id, slice_id, kind, content):
    return {"id": mem_id, "scope": "durable", "slice_id": slice_id, "commit": None,
            "kind": kind, "content": content, "attempt": None, "edges": []}


def _legacy_commit_and_note(root, message, slice_id, files, used):
    git(root, "init", "-q", "-b", "main")
    for key, value in (("user.email", "t@t"), ("user.name", "t"),
                       ("maintenance.auto", "false"), ("gc.auto", "0")):
        git(root, "config", key, value)
    git(root, "add", "-A")
    git(root, "commit", "-qm", message)
    payload = [{"memory_ids": [], "modules_touched": files,
                "registry_used": used, "slice_id": slice_id}]
    git(root, "notes", "--ref=refs/notes/harness", "add", "-f", "-m",
        json.dumps(payload, sort_keys=True), "HEAD")


def build_legacy_08_repo(root: Path) -> Path:
    """A 0.8.0 substrate after real use: EDIT-ME seed rows, no vendored
    engine, a pre-0.9.1 `deps:` G5 override, committed shadows, telemetry,
    durable memory, a contract stub, one closed and one in-flight slice."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    hd = root / ".harness"
    _write(root, ".harness/config.yaml", _legacy_config("0.8.0"))
    _write(root, ".harness/schema_version", "1\n")
    _write(root, "telemetry.py", TELEMETRY_PY)
    _write(root, "config.py", CONFIG_PY)
    _write(root, "orders.py", ORDERS_PY)
    _write(root, "tests/slices/040_telemetry.py",
           "import telemetry\n\n\ndef test_emit_span():\n"
           "    assert telemetry.emit_span('x', {})['name'] == 'x'\n")
    _write(root, "tests/slices/042_orders.py",
           "def test_orders():\n    import orders\n    assert orders.create_order('x')\n")
    shadows = {rel: _legacy_shadow(root, rel, exports) for rel, exports in (
        ("telemetry.py", ["emit_span"]), ("config.py", ["get_config"]),
        ("orders.py", ["create_order"]),
        ("tests/slices/040_telemetry.py", ["test_emit_span"]))}
    seed = [json.loads(line) for line in
            (LEGACY_DIR / "registry-seed-0.8.0.jsonl").read_text().splitlines() if line.strip()]
    write_jsonl(hd / "registry.jsonl", [r for r in seed if r["id"] != "config"] + [
        _legacy_entry("config", "config", "built", "config.py", CONFIG_PY, shadows["config.py"]),
        _legacy_entry("telemetry", "telemetry", "built", "telemetry.py", TELEMETRY_PY,
                      shadows["telemetry.py"]),
        _legacy_entry("orders", "component", "planned", "orders.py")])
    _write(root, ".harness/decisions.jsonl",
           (LEGACY_DIR / "decisions-seed-0.8.0.jsonl").read_text())
    backlog_seed = [json.loads(line) for line in
                    (LEGACY_DIR / "backlog-seed-0.8.0.jsonl").read_text().splitlines()
                    if line.strip()]
    write_jsonl(hd / "backlog.jsonl", backlog_seed + [
        {"id": "slice-040", "spec": "spec-007", "title": "telemetry module",
         "status": "closed", "declares_dep": ["telemetry"],
         "acceptance": ["tests/slices/040_telemetry.py"],
         "predicted_files": ["telemetry.py"], "context_cost_estimate": 0,
         "depends_on": [], "worktree": None},
        {"id": "slice-042", "spec": "spec-007", "title": "orders service",
         "status": "in_progress", "declares_dep": ["telemetry", "config"],
         "acceptance": ["tests/slices/042_orders.py"],
         "predicted_files": ["orders.py"], "context_cost_estimate": 0,
         "depends_on": ["slice-040"], "worktree": None}])
    write_jsonl(hd / "edges.jsonl", [
        _legacy_edge("declares_dep", "slice:slice-040", "module:telemetry"),
        _legacy_edge("uses", "slice:slice-040", "module:telemetry"),
        _legacy_edge("uses", "slice:slice-040", "module:config"),
        _legacy_edge("override", "slice:slice-040", "deps:config",
                     {"rule_ref": "gate:G5", "finding_id": "F-legacy-g5",
                      "justification": "config read approved in review"}),
        _legacy_edge("override", "slice:slice-040", "file:telemetry.py",
                     {"rule_ref": "gate:G2", "finding_id": "F-legacy-g2",
                      "justification": "context loaded by hand"})])
    write_jsonl(hd / "boundaries.jsonl", [
        {"id": "B-legacy", "source_adr": "007", "rule_ref": "adr:007",
         "text": "legacy exporter out of scope", "patterns": ["legacy/**"]}])
    _write(root, ".harness/notes.jsonl", "")
    write_jsonl(hd / "telemetry.jsonl", legacy_events("slice-040", 3, 4)
                + [_closed_event("slice-040", 3)] + legacy_events("slice-042", 5, 3))
    write_jsonl(hd / "memory" / "durable.jsonl", [
        _durable("mem-0a1b2c3d4e5f", "slice-040", "observation",
                 "Span names use snake_case verb_noun.")])
    _write(root, ".harness/memory/session/slice-042.jsonl",
           json.dumps({"id": "mem-session1", "scope": "session", "slice_id": "slice-042",
                       "kind": "reasoning", "content": "orders reads config"}) + "\n")
    _write(root, "AGENTS.md", (LEGACY_DIR / "agents-md-0.8.0.md").read_text())
    _write(root, "CLAUDE.md", LEGACY_CLAUDE_MD)
    _write(root, ".github/workflows/harness-verify.yml",
           (LEGACY_DIR / "ci-verify-0.8.0.yml").read_text())
    _write(root, ".claude/settings.json", _legacy_settings(root))
    _write(root, "adr/000-template.md", "# ADR-000: template\n")
    _write(root, "adr/007-telemetry.md", ADR_007)
    _write(root, "contracts/api.yaml", CONTRACT_STUB)
    _write(root, "pytest.ini", LEGACY_PYTEST_INI)
    _write(root, ".gitignore", LEGACY_GITIGNORE)
    _write(root, ".gitattributes", LEGACY_GITATTRIBUTES)
    _legacy_commit_and_note(root, "harness 0.8.0 substrate", "slice-040",
                            ["telemetry.py"], ["telemetry"])
    return root


def build_astralabs_094_repo(root: Path, *, marked: bool = True) -> Path:
    """A 0.9.4 substrate with the astralabs layout: `libs/**/src` packages,
    tests, an ignored mkdocs `site/` with a `.js.map`, a tracked mp4,
    committed shadows (with `site/` and test shadows), telemetry and its
    archive, durable memory, a contract stub, path-only non-goals, G2/G3/G7
    overrides, a stale vendored engine, one closed and one in-flight slice.
    `marked=False` writes hand-authored AGENTS.md and CLAUDE.md."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    hd = root / ".harness"
    for rel, text in {
        "libs/core/src/astra_core/__init__.py": '"""Astra core services."""\n',
        "libs/core/src/astra_core/config.py": ASTRA_CONFIG_PY,
        "libs/core/src/astra_core/orders.py": ASTRA_ORDERS_PY,
        "libs/billing/src/astra_billing/__init__.py": '"""Astra billing."""\n',
        "libs/billing/src/astra_billing/invoice.py": ASTRA_INVOICE_PY,
        "tests/unit/test_config.py": ("from astra_core.config import get_setting\n\n\n"
                                      "def test_default():\n"
                                      "    assert get_setting('x', 1) == 1\n"),
        "tests/slices/041_invoice.py": ("from astra_billing.invoice import total\n\n\n"
                                        "def test_total():\n"
                                        "    assert total([1.0, 2.5]) == 3.5\n"),
        "tests/slices/043_orders.py": ("from astra_core.orders import create_order\n\n\n"
                                       "def test_create_order():\n"
                                       "    assert create_order('a1')['currency'] == 'CAD'\n"),
        "mkdocs.yml": "site_name: Astra\nnav:\n  - Home: index.md\n",
        "docs/index.md": "# Astra\n\nOrder intake and billing.\n",
        "pytest.ini": ASTRA_PYTEST_INI,
        "adr/001-config.md": "# ADR-001: settings\n\nServices read settings through get_setting.\n",
        "adr/003-scope.md": "# ADR-003: scope\n\nThe docs site and media are out of scope.\n",
        "site/index.html": "<html><body>Astra</body></html>\n",
        "site/assets/javascripts/bundle.js": "var a=1;\n" * 400,
        "site/assets/javascripts/bundle.js.map": json.dumps(
            {"version": 3, "sources": ["bundle.ts"], "mappings": "AAAA;" * 2000}),
    }.items():
        _write(root, rel, text)
    _write(root, "assets/demo.mp4", b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * 256)
    shadows = {rel: _legacy_shadow(root, rel, exports) for rel, exports in (
        ("libs/core/src/astra_core/config.py", ["get_setting"]),
        ("libs/core/src/astra_core/orders.py", ["create_order"]),
        ("libs/billing/src/astra_billing/invoice.py", ["total"]),
        ("tests/unit/test_config.py", ["test_default"]),
        ("tests/slices/041_invoice.py", ["test_total"]),
        ("site/assets/javascripts/bundle.js", ["a"]))}
    _write(root, ".harness/config.yaml", _legacy_config(
        "0.9.4", extra='extractor:\n  src_roots: ["libs/*/src"]\n'))
    _write(root, ".harness/schema_version", "1\n")
    write_jsonl(hd / "registry.jsonl", [
        _legacy_entry("config", "config", "built", "libs/core/src/astra_core/config.py",
                      ASTRA_CONFIG_PY, shadows["libs/core/src/astra_core/config.py"]),
        _legacy_entry("billing", "component", "built",
                      "libs/billing/src/astra_billing/invoice.py", ASTRA_INVOICE_PY,
                      shadows["libs/billing/src/astra_billing/invoice.py"]),
        _legacy_entry("orders", "component", "planned", "libs/core/src/astra_core/orders.py"),
        _legacy_entry("logging", "logging", "planned"),
        _legacy_entry("errors", "errors", "planned")])
    write_jsonl(hd / "decisions.jsonl", [
        {"id": "D-001", "domain": "config", "question": "How do services read settings?",
         "answer": "Through astra_core.config.get_setting only.",
         "adr_ref": "adr/001-config.md", "origin": "phase0",
         "created": "2026-08-01T00:00:00+00:00"}])
    write_jsonl(hd / "backlog.jsonl", [
        {"id": "slice-041", "spec": "spec-001", "title": "billing invoices",
         "status": "closed", "declares_dep": ["billing"],
         "acceptance": ["tests/slices/041_invoice.py"],
         "predicted_files": ["libs/billing/src/astra_billing/invoice.py"],
         "context_cost_estimate": 0, "depends_on": [], "worktree": None,
         "landed_via": "local"},
        {"id": "slice-043", "spec": "spec-001", "title": "order intake",
         "status": "in_progress", "declares_dep": ["config"],
         "acceptance": ["tests/slices/043_orders.py"],
         "predicted_files": ["libs/core/src/astra_core/orders.py"],
         "context_cost_estimate": 0, "depends_on": ["slice-041"], "worktree": None}])
    write_jsonl(hd / "boundaries.jsonl", [
        {"id": "B-site", "source_adr": "003", "rule_ref": "adr:003",
         "text": "the docs site build is out of scope", "patterns": ["site/**"]},
        {"id": "B-assets", "source_adr": "003", "rule_ref": "adr:003",
         "text": "media assets are out of scope", "patterns": ["assets/**"]}])
    write_jsonl(hd / "edges.jsonl", [
        _legacy_edge("declares_dep", "slice:slice-041", "module:billing"),
        _legacy_edge("uses", "slice:slice-041", "module:billing"),
        _legacy_edge("override", "slice:slice-041", "file:site/assets/javascripts/bundle.js",
                     {"rule_ref": "gate:G7", "finding_id": "F-g7-1",
                      "justification": "mkdocs rebuilt site/; the shadow drift is not ours"}),
        _legacy_edge("override", "slice:slice-041",
                     "file:libs/billing/src/astra_billing/invoice.py",
                     {"rule_ref": "gate:G2", "finding_id": "F-g2-1",
                      "justification": "read the module by hand"}),
        _legacy_edge("override", "slice:slice-043", "boundary:B-site",
                     {"rule_ref": "gate:G3", "finding_id": "F-g3-1",
                      "justification": "docs nav entry for orders"}),
        _legacy_edge("override", "slice:slice-043", "boundary:B-assets",
                     {"rule_ref": "gate:G3", "finding_id": "F-g3-2",
                      "justification": "demo clip for orders"})])
    _write(root, ".harness/notes.jsonl", "")
    write_jsonl(hd / "telemetry.archive.jsonl",
                legacy_events("slice-041", 2, 6) + [_closed_event("slice-041", 2)])
    write_jsonl(hd / "telemetry.jsonl", legacy_events("slice-043", 9, 5))
    write_jsonl(hd / "memory" / "durable.jsonl", [
        _durable("mem-1a2b3c4d5e6f", "slice-041", "observation",
                 "Invoices round half-even to cents."),
        _durable("mem-6f5e4d3c2b1a", "slice-041", "reasoning",
                 "Billing never imports astra_core.orders.")])
    _write(root, ".harness/memory/session/slice-043.jsonl",
           json.dumps({"id": "mem-session2", "scope": "session", "slice_id": "slice-043",
                       "kind": "reasoning", "content": "orders default to CAD"}) + "\n")
    _write(root, ".harness/engine/VERSION", "0.9.4\n")
    _write(root, ".harness/engine/bin/harness", "#!/usr/bin/env python3\n")
    _write(root, ".harness/engine/engine/__init__.py", 'ENGINE_VERSION = "0.9.4"\n')
    _write(root, ".harness/engine/README.md", "# vendored harness engine\n")
    _write(root, "contracts/api.yaml", CONTRACT_STUB)
    _write(root, ".github/workflows/harness-verify.yml",
           (LEGACY_DIR / "ci-verify-0.9.4.yml").read_text())
    _write(root, ".claude/settings.json", _legacy_settings(root))
    if marked:
        _write(root, "AGENTS.md", (LEGACY_DIR / "agents-md-0.9.4.md").read_text())
        _write(root, "CLAUDE.md", LEGACY_CLAUDE_MD)
    else:
        _write(root, "AGENTS.md", UNMARKED_AGENTS_MD)
        _write(root, "CLAUDE.md", UNMARKED_CLAUDE_MD)
    _write(root, ".gitignore", LEGACY_GITIGNORE + "/site/\n")
    _write(root, ".gitattributes", LEGACY_GITATTRIBUTES)
    _legacy_commit_and_note(root, "astralabs at harness 0.9.4", "slice-041",
                            ["libs/billing/src/astra_billing/invoice.py"], ["billing"])
    return root


def write_legacy_sidecar(root, binding, buffered):
    """A 0.9 `.harness/sidecar.db`: one session bound to a slice, plus
    telemetry rows that were never flushed."""
    import sqlite3
    db = sqlite3.connect(str(Path(root) / ".harness" / "sidecar.db"))
    try:
        db.executescript(LEGACY_SIDECAR_DDL)
        session, slice_id = binding
        db.execute("INSERT INTO session_state VALUES (?, 'active_slice', ?)",
                   (session, json.dumps(slice_id)))
        for row in buffered:
            db.execute("INSERT INTO telemetry_buffer(row) VALUES (?)",
                       (json.dumps(row, sort_keys=True),))
        db.commit()
    finally:
        db.close()


def tree_bytes(root) -> dict:
    """Every file under root, by bytes, ignored files included. Excludes git
    internals, gitignored machine state and Python caches."""
    root = Path(root)
    out = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if (path.is_dir() or rel.startswith(MACHINE_STATE)
                or "__pycache__" in path.parts or ".pytest_cache" in path.parts):
            continue
        out[rel] = path.read_bytes()
    return out
