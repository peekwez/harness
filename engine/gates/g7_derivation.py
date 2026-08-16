"""G7 derivation-integrity: all derived artifacts regenerate identically.

Catches hand-edited shadows (hand-editing a derived file is, by definition,
a bug). Runs at unit_complete and in CI via `harness verify`.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..events import make_finding
from ..extractor.engine import build_shadow, LANG_BY_EXT, load_shadow_file, shadow_path_for

GATE = {"id": "G7", "rule_ref": "gate:G7",
        "preferred": ("unit_complete",), "fallback": ()}


def derivation_findings(root, config, paths=None, since_ns=None) -> list:
    """Shared with C9 verify. Regenerate shadows in memory, byte-compare.

    `since_ns` skips shadows untouched since a previous verified sweep — a
    pure cache (absence = do the work), so the guarantee is unchanged while
    the Stop hook stops being O(repo) tree-sitter parses (review R4). CI
    verify passes nothing and always sweeps everything.
    """
    from ..extractor.engine import DEP_INSTALL_HINT, deps_available
    root = Path(root)
    findings = []
    shadows_dir = root / ".harness" / "shadows"
    if not shadows_dir.exists():
        return findings
    if not deps_available():
        # Degraded, not blocked: regeneration is impossible without the
        # extraction stack, and that fact is surfaced loudly every run.
        return [make_finding(
            "MISSING_DEPENDENCY", GATE["rule_ref"],
            f"derivation-integrity checks skipped: tree-sitter stack "
            f"unavailable — run `{DEP_INSTALL_HINT}`",
            severity="advisory", key="g7-deps")]
    for sp in sorted(shadows_dir.rglob("*.json")):
        # verified in an earlier sweep and untouched since: a hand-edit
        # always moves mtime forward, so skipping here cannot hide one
        if since_ns is not None and sp.stat().st_mtime_ns < since_ns:
            continue
        try:
            stored = load_shadow_file(sp)
        except json.JSONDecodeError:
            findings.append(make_finding(
                "DERIVATION_MISMATCH", GATE["rule_ref"],
                f"{sp.relative_to(root)}: unparseable shadow (hand-edited?)",
                severity="block", key=str(sp)))
            continue
        src = root / stored.get("source_path", "")
        from ..extractor.engine import in_root
        if not in_root(root, src):
            # a traversal source_path is a corrupt derived artifact; raising
            # here bricked EVERY hook fail-closed with a raw error (S5) —
            # report it as the finding it is instead
            findings.append(make_finding(
                "DERIVATION_MISMATCH", GATE["rule_ref"],
                f"{sp.relative_to(root)}: source_path "
                f"{stored.get('source_path')!r} escapes the repo root; "
                f"corrupt derived artifact — run `harness extract --all` "
                f"(prunes it)", severity="block", key=str(sp) + "|oor"))
            continue
        if not src.exists():
            findings.append(make_finding(
                "DERIVATION_MISMATCH", GATE["rule_ref"],
                f"{sp.relative_to(root)}: source {stored.get('source_path')!r} "
                f"no longer exists; stale derived artifact — run "
                f"`harness extract --all` (prunes it)",
                severity="block", key=str(sp) + "|gone"))
            continue
        if paths is not None and str(src.resolve()) not in paths:
            continue
        lang = LANG_BY_EXT.get(src.suffix.lower())
        source = src.read_bytes()
        if lang is None or not (config or {}).get("languages", {}).get(lang, True):
            from ..extractor.engine import _degenerate_shadow
            regen = _degenerate_shadow(root, src, source, config)
        else:
            regen = build_shadow(root, src, source, lang, config)
        # byte-level: "regenerates identically" includes formatting — a
        # reformatted shadow is still a hand-edited derived artifact
        stored_bytes = sp.read_bytes()
        regen_bytes = (json.dumps(regen, sort_keys=True, indent=1) + "\n").encode("utf-8")
        if stored_bytes != regen_bytes:
            # name a fix that CANNOT no-op: --force bypasses the cache
            # entirely, so the finding and the fix never contradict (X2)
            findings.append(make_finding(
                "DERIVATION_MISMATCH", GATE["rule_ref"],
                f"{sp.relative_to(root)} does not regenerate identically from "
                f"{stored.get('source_path')}; derived artifacts must never be "
                f"hand-edited — run `harness extract --force "
                f"{stored.get('source_path')}`",
                severity="block", key=str(sp) + "|diff"))
    return findings


def check(ctx) -> list:
    """Every shadow still gets verified — but a shadow proven identical in
    an earlier sweep and untouched since is skipped, so the Stop hook costs
    O(changed) parses instead of O(repo) (review R4). The sweep timestamp is
    taken BEFORE the work, so anything modified mid-sweep is re-checked."""
    import time
    since = ctx.sidecar.state_get("__g7__", "last_sweep_ns")
    started = time.time_ns()
    findings = derivation_findings(ctx.root, ctx.config, since_ns=since)
    if not findings:
        # only a clean sweep may advance the watermark: a repo with a
        # standing mismatch must keep reporting it every time
        ctx.sidecar.state_set("__g7__", "last_sweep_ns", started)
    return findings
