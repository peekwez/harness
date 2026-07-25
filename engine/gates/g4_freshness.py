"""G4 shadow-fresh: loaded shadow hashes match current source.

The parallel-agent staleness net (T5): worktree-per-slice partitions by
construction; G4 at merge is the safety net.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import sha256_file
from ..events import make_finding

GATE = {"id": "G4", "rule_ref": "gate:G4",
        "preferred": ("pre_change", "unit_complete"), "fallback": ()}


def check(ctx) -> list:
    findings = []
    registry = {e["id"]: e for e in ctx.registry}
    for item in sorted(ctx.context_loaded):
        if not item.startswith("shadow:"):
            continue
        entry = registry.get(item.split(":", 1)[1])
        if entry is None or not entry.get("shadow") or not entry.get("source"):
            continue
        sp = ctx.root / entry["shadow"]
        src = ctx.root / entry["source"]
        if not sp.exists() or not src.exists():
            continue  # G1/G7 own missing artifacts
        shadow = json.loads(sp.read_text())
        current = sha256_file(src)
        if shadow.get("source_hash") != current:
            findings.append(make_finding(
                "STALE_SHADOW", GATE["rule_ref"],
                f"loaded {item} is stale: source {entry['source']} changed since "
                f"the shadow was generated",
                severity="block",
                inject=[f"refresh: run `harness extract {entry['source']}` then "
                        f"reload {entry['shadow']}"],
                key=item))
    return findings
