"""G2 context-loaded: the touched file's domain context is in this session.

Phase-2 verification. Blocks are the exception path: the deny reason carries a
pointer-sized correction (path + signature summary, <=400 tokens), never a
full shadow dump — full shadows go through Phase 1 under budget control.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..events import make_finding
from .. import token_estimate

GATE = {"id": "G2", "rule_ref": "gate:G2",
        "preferred": ("pre_change",), "fallback": ("post_change",)}

POINTER_TOKEN_CAP = 400


def _pointer(root, entry) -> str:
    """Pointer-sized correction: shadow path + exported signature summary."""
    lines = [f"load shadow: {entry.get('shadow')}"]
    sp = Path(root) / (entry.get("shadow") or "")
    if entry.get("shadow") and sp.exists():
        shadow = json.loads(sp.read_text())
        for s in shadow.get("symbols", [])[:12]:
            if s.get("visibility") == "public":
                lines.append(s["signature"])
    text = "\n".join(lines)
    while token_estimate(text) > POINTER_TOKEN_CAP and len(lines) > 1:
        lines.pop()
        text = "\n".join(lines)
    return text


def check(ctx) -> list:
    if not ctx.work_unit_id:
        return [make_finding(
            "NO_ACTIVE_WORK_UNIT", GATE["rule_ref"],
            "no active work unit bound to this session; run /harness:build "
            "to bind a slice (G2 context checks are per-slice)",
            severity="advisory", key=ctx.session_id)]
    findings = []
    loaded = ctx.context_loaded
    registry = {e["id"]: e for e in ctx.registry}
    from .g3_scope import SUBSTRATE_PREFIXES as substrate_prefixes
    touched = [ctx.rel(p) for p in ctx.touched_files()]
    deps = ctx.slice.get("declares_dep", [])
    for rel in touched:
        if rel.startswith(substrate_prefixes):
            continue
        required = []
        own = next((e for e in ctx.registry if e.get("source") == rel), None)
        for did in deps + ([own["id"]] if own else []):
            entry = registry.get(did)
            if entry is None:
                continue
            if entry.get("status") == "built":
                item = f"shadow:{did}"
                if item not in loaded:
                    required.append((item, entry))
            else:
                for ref in entry.get("guidance_refs", []):
                    from ..resolver import _adr_id
                    item = _adr_id(ref)
                    if item not in loaded:
                        required.append((item, entry))
        for item, entry in required:
            shadow_exists = entry.get("shadow") and (ctx.root / entry["shadow"]).exists()
            code = ("CONTEXT_NOT_LOADED" if shadow_exists or not item.startswith("shadow:")
                    else "MISSING_SHADOW")
            findings.append(make_finding(
                code, GATE["rule_ref"],
                f"{rel}: required context {item!r} not loaded this session "
                f"(Phase-1 injection missed it — frequent G2 blocks indicate an "
                f"upstream declaration defect)",
                severity="block",
                inject=[_pointer(ctx.root, entry)] if item.startswith("shadow:") else
                       [f"read: {r}" for r in entry.get("guidance_refs", [])],
                key=rel + "|" + item))
    return findings
