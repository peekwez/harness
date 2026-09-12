"""G7 derivation-integrity: all derived artifacts regenerate identically.

Catches hand-edited shadows (hand-editing a derived file is, by definition,
a bug). Runs at unit_complete and in CI via `harness verify`.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import IGNORED_DIRS, IGNORED_EXTS, load_backlog, sha256_bytes
from ..events import make_finding
from ..extractor.engine import (LANG_BY_EXT, build_shadow, load_shadow_file,
                                shadow_path_for)
from ..extractor.modules import python_module_ids

GATE = {"id": "G7", "rule_ref": "gate:G7",
        "preferred": ("unit_complete",), "fallback": ()}


def _required_shadow_sources(root, config) -> dict[Path, Path]:
    """Expected shadow path -> source for explicitly enforced source files.

    Registry sources are part of the substrate even while planned. Modern
    closed slices also promise derivation coverage for their recorded files.
    This intentionally does not turn every repository file into a Stop-hook
    requirement; ``extract --all`` remains the explicit full discovery pass.
    """
    from ..extractor.engine import in_root
    from ..registry import load_registry

    root = Path(root)
    candidates = [entry.get("source") for entry in load_registry(root)]
    candidates.extend(
        path
        for sl in load_backlog(root)
        if sl.get("status") == "closed" and sl.get("provenance_version")
        for path in sl.get("closed_files", [])
    )
    required = {}
    for rel in candidates:
        if not isinstance(rel, str):
            continue
        rel_path = Path(rel)
        if (rel_path.is_absolute() or ".." in rel_path.parts
                or any(part in IGNORED_DIRS for part in rel_path.parts)
                or rel_path.suffix.lower() in IGNORED_EXTS):
            continue
        source = root / rel_path
        if not in_root(root, source) or not source.is_file():
            continue
        required[shadow_path_for(root, source)] = source
    return required


def _source_for_shadow_path(root: Path, shadow: Path) -> Path | None:
    """Recover the source path encoded by ``shadow_path_for`` safely."""
    shadows_dir = (root / ".harness" / "shadows").resolve()
    try:
        rel = shadow.resolve().relative_to(shadows_dir)
    except ValueError:
        return None
    if not rel.name.endswith(".json"):
        return None
    source_rel = Path(str(rel)[:-len(".json")])
    if (any(part in IGNORED_DIRS for part in source_rel.parts)
            or source_rel.suffix.lower() in IGNORED_EXTS):
        return None
    source = root / source_rel
    from ..extractor.engine import in_root
    return source if in_root(root, source) and source.is_file() else None


def derivation_findings(root, config, paths=None, since_ns=None,
                        shadow_paths=None) -> list:
    """Shared with C9 verify. Regenerate shadows in memory, byte-compare.

    ``shadow_paths`` may restrict regeneration to artifacts whose complete
    input fingerprint changed since a previous clean sweep. ``since_ns`` is
    retained for callers from older releases but is deliberately not trusted:
    a source/config/extractor change need not move the shadow mtime. CI verify
    passes neither argument and always sweeps everything.
    """
    from ..extractor.engine import DEP_INSTALL_HINT, deps_available
    root = Path(root)
    findings = []
    shadows_dir = root / ".harness" / "shadows"
    selected = ({str(Path(p).resolve()) for p in shadow_paths}
                if shadow_paths is not None else None)
    reported_missing = set()
    for sp, src in sorted(_required_shadow_sources(root, config).items()):
        if selected is not None and str(sp.resolve()) not in selected:
            continue
        if paths is not None and str(src.resolve()) not in paths:
            continue
        if not sp.is_file():
            reported_missing.add(str(sp.resolve()))
            findings.append(make_finding(
                "DERIVATION_MISMATCH", GATE["rule_ref"],
                f"{sp.relative_to(root)} is missing for required source "
                f"{src.relative_to(root)} — run `harness extract --force "
                f"{src.relative_to(root)}`",
                severity="block", key=str(sp) + "|missing"))
    # An incremental fingerprint cache is also an explicit promise about the
    # artifacts it observed. If one disappears while its source remains, the
    # removed key must not vanish silently from the next clean cache state.
    for raw in sorted(selected or ()):
        sp = Path(raw)
        if sp.is_file() or raw in reported_missing:
            continue
        src = _source_for_shadow_path(root, sp)
        if src is None or (paths is not None and str(src.resolve()) not in paths):
            continue
        findings.append(make_finding(
            "DERIVATION_MISMATCH", GATE["rule_ref"],
            f"{sp.relative_to(root)} disappeared for source "
            f"{src.relative_to(root)} — run `harness extract --force "
            f"{src.relative_to(root)}`",
            severity="block", key=str(sp) + "|missing"))
    if not deps_available():
        # Degraded, not blocked: regeneration is impossible without the
        # extraction stack, and that fact is surfaced loudly every run.
        findings.append(make_finding(
            "MISSING_DEPENDENCY", GATE["rule_ref"],
            f"derivation-integrity checks skipped: tree-sitter stack "
            f"unavailable — run `{DEP_INSTALL_HINT}`",
            severity="advisory", key="g7-deps"))
        return findings
    if not shadows_dir.exists():
        return findings
    known_modules = python_module_ids(root, config)
    for sp in sorted(shadows_dir.rglob("*.json")):
        if selected is not None and str(sp.resolve()) not in selected:
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
            regen = build_shadow(root, src, source, lang, config,
                                 known_modules=known_modules)
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


def _input_fingerprints(root, config) -> dict:
    """Cheap, safe G7 cache keys for every stored shadow.

    The fingerprint covers both sides of the derivation and all context that
    can alter module identity/import resolution. Reading bytes is much cheaper
    than parsing every source, while backdated mtimes cannot hide a change.
    """
    from ..extractor import engine as extractor

    root = Path(root)
    shadows_dir = root / ".harness" / "shadows"
    known_modules = python_module_ids(root, config)
    context = json.dumps({
        "deps_available": extractor.deps_available(),
        "extractor": (config or {}).get("extractor"),
        "extractor_version": extractor.EXTRACTOR_VERSION,
        "languages": (config or {}).get("languages", {}),
    }, sort_keys=True, separators=(",", ":")).encode()
    out = {}
    required = _required_shadow_sources(root, config)
    shadow_paths = set(shadows_dir.rglob("*.json")) | set(required)
    for sp in sorted(shadow_paths):
        shadow_bytes = sp.read_bytes() if sp.is_file() else b"<missing>"
        source_bytes = b"<unavailable>"
        resolution = b"{}"
        try:
            stored = json.loads(shadow_bytes)
            candidates = stored.get("import_candidates", [])
            if isinstance(candidates, list):
                resolution = json.dumps(
                    {name: name in known_modules for name in candidates
                     if isinstance(name, str)},
                    sort_keys=True, separators=(",", ":")).encode()
            rel = stored.get("source_path")
            src = root / rel if isinstance(rel, str) else None
            if (src is not None and extractor.in_root(root, src)
                    and src.is_file()):
                source_bytes = src.read_bytes()
        except (json.JSONDecodeError, OSError):
            source = required.get(sp)
            if source is not None:
                source_bytes = source.read_bytes()
        payload = b"\0".join((context, resolution, shadow_bytes, source_bytes))
        out[str(sp.relative_to(root))] = sha256_bytes(payload)
    return out


def check(ctx) -> list:
    """Regenerate only shadows whose complete derivation inputs changed."""
    previous = ctx.sidecar.state_get("__g7__", "input_fingerprints")
    current = _input_fingerprints(ctx.root, ctx.config)
    selected = None
    if previous is not None:
        selected = {
            Path(ctx.root) / rel
            for rel in set(previous) | set(current)
            if previous.get(rel) != current.get(rel)
        }
    findings = derivation_findings(
        ctx.root, ctx.config, shadow_paths=selected)
    if not findings:
        # Only clean inputs are cached. A standing mismatch therefore remains
        # selected and reported until its shadow is regenerated.
        ctx.sidecar.state_set("__g7__", "input_fingerprints", current)
    return findings
