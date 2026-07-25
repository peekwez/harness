"""Layer 0 — deterministic fact assembly.

Gate outputs, uses/declares diff, duplicate candidates, decision rows in
scope, shadows of everything the diff imports. No model, no judgment.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .. import get_slice, load_decisions
from ..extractor.engine import LANG_BY_EXT, shadow_path_for
from ..graph import uses_vs_declares
from ..registry import load_registry


def diff_files(diff_text: str) -> list:
    files = []
    for m in re.finditer(r"^\+\+\+ b/(.+)$", diff_text or "", re.M):
        files.append(m.group(1))
    for m in re.finditer(r"^diff --git a/(\S+) b/(\S+)$", diff_text or "", re.M):
        if m.group(2) not in files:
            files.append(m.group(2))
    return files


def assemble(root, diff_text: str, slice_id: str, config: dict) -> dict:
    """Substrate + diff only. The reviewer never receives builder session
    memory — independent derivation from the same ground truth is the point."""
    root = Path(root)
    registry = load_registry(root)
    files = diff_files(diff_text)

    # gate outputs (post_change + unit_complete packs, dry over the diff files)
    from ..events import Sidecar
    from ..gates import run_gates
    sidecar = Sidecar(root)
    try:
        gate_findings = []
        for event_name in ("post_change", "unit_complete"):
            evt = {"event": event_name, "session_id": f"review:{slice_id}",
                   "work_unit_id": slice_id,
                   "payload": {"files": [{"path": f, "proposed_content_hash": None}
                                         for f in files],
                               "context_loaded": [], "diff": diff_text, "prompt": None}}
            gate_findings.extend(run_gates(root, evt, config, sidecar))
    finally:
        sidecar.close()

    ud = uses_vs_declares(root, slice_id)
    sl = get_slice(root, slice_id)
    domains = set()
    reg_by_id = {e["id"]: e for e in registry}
    for did in sl.get("declares_dep", []):
        if did in reg_by_id:
            domains.add(reg_by_id[did].get("kind", "other"))
    decisions_in_scope = [d for d in load_decisions(root)
                          if d.get("domain") in domains]

    dup_candidates = [f for f in gate_findings if f["code"] == "DUPLICATE_CANDIDATE"]

    imported_shadows = {}
    for f in files:
        if Path(f).suffix.lower() not in LANG_BY_EXT:
            continue
        sp = shadow_path_for(root, root / f)
        if not sp.exists():
            continue
        shadow = json.loads(sp.read_text())
        for imp in shadow.get("imports", []):
            entry = reg_by_id.get(imp)
            if entry and entry.get("shadow") and (root / entry["shadow"]).exists():
                imported_shadows[imp] = json.loads((root / entry["shadow"]).read_text())

    return {
        "slice": slice_id,
        "diff_files": files,
        "gate_findings": gate_findings,
        "uses_declares": ud,
        "duplicate_candidates": dup_candidates,
        "decisions_in_scope": decisions_in_scope,
        "imported_shadows": {k: {"module_id": v["module_id"],
                                 "exports": v.get("exports"),
                                 "symbols": [s["signature"] for s in v.get("symbols", [])
                                             if s.get("visibility") == "public"]}
                             for k, v in sorted(imported_shadows.items())},
    }
