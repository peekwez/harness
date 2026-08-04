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


# Deterministic secret patterns over ADDED diff lines. Deliberately narrow:
# a false-positive storm teaches agents to override reflexively. Findings
# never echo the matched text — a report that repeats the secret IS a leak.
SECRET_PATTERNS = (
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private-key-block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY")),
    ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("slack-token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("assigned-credential", re.compile(
        r"(?i)\b(api[_-]?key|secret|token|passw(?:or)?d)\b[\"']?\s*[:=]"
        r"\s*[\"'][A-Za-z0-9+/_\-]{16,}[\"']")),
)


def _secret_findings(root, diff_text, slice_id):
    """Layer-0 secret scan (the seed-leak class, caught deterministically on
    every slice — not only when a fork reviewer runs). A recorded override
    edge `secret:<file>` downgrades a named false positive, auditable."""
    from ..events import make_finding
    from ..graph import load_edges
    findings, current = [], None
    overridden = {e["to"].split(":", 1)[-1] for e in load_edges(root)
                  if e["from"] == f"slice:{slice_id}"
                  and e["type"] == "override" and e["to"].startswith("secret:")}
    for line in (diff_text or "").splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                sev = "advisory" if current in overridden else "block"
                findings.append(make_finding(
                    "SECRET_IN_DIFF", "review:layer0",
                    f"{current or '<unknown file>'}: added line matches the "
                    f"{label} pattern"
                    + (" (override recorded — audited)" if sev == "advisory"
                       else " — remove it, or record a false-positive "
                            "override: `harness gates override --slice "
                            f"{slice_id} --target secret:{current} "
                            "--rule-ref review:layer0 --justification "
                            '"<why>"`'),
                    severity=sev, key=f"{current}|{label}"))
                break
    return findings


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
    gate_findings.extend(_secret_findings(root, diff_text, slice_id))

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
