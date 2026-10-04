"""C5 — Resolver: slice -> prioritized context blocks under one cap.

Deterministic: same slice + same substrate -> byte-identical output. Five
blocks in a fixed priority order (findings, decision rows, non-goals, slice
card, module pointers). When they do not fit MAX_INJECTION_CHARS the lowest
priority is cut first and each cut block becomes a one-line pointer. Module
shadows and guidance are never injected: a module is a pointer to
`harness resolve --module <id>`.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from . import (SubstrateMissing, get_slice, harness_dir, load_boundaries,
               load_decisions, read_jsonl)
from .registry import load_registry

MAX_INJECTION_CHARS = 9000
BLOCK_SEPARATOR = "\n\n"
# lower number = higher priority; the cap cuts the highest number first
BLOCK_PRIORITY = {"findings": 1, "decisions": 2, "non-goals": 3,
                  "slice": 4, "modules": 5}
MODULES_TITLE = "modules (full context: harness resolve --module <id>)"


def _adr_id(ref: str) -> str:
    """'adr/007-telemetry.md#s2' -> 'adr:007'."""
    m = re.search(r"adr/(\d+)", ref)
    return f"adr:{m.group(1)}" if m else f"adr:{ref}"


def render_shadow(shadow: dict, with_docs: bool = True) -> str:
    lines = [f"=== shadow:{shadow['module_id']} ({shadow['source_path']}) ==="]
    for s in shadow.get("symbols", []):
        if s.get("visibility") != "public":
            continue
        lines.append(s["signature"])
        if with_docs and s.get("doc"):
            lines.append(f"  # {s['doc'].splitlines()[0]}")
    exports = shadow.get("exports")
    lines.append(f"exports: {exports if isinstance(exports, str) else ', '.join(exports)}")
    return "\n".join(lines)


_ADR_STATUS_CACHE: dict = {}


def _adr_superseded_ids(root) -> set:
    """ADR ids that are out of force: status superseded, or listed in another
    ADR's `supersedes`. Injecting them alongside their replacement hands the
    builder contradictory guidance (field report #15)."""
    adr_dir_ = Path(root) / "adr"
    sig = tuple(sorted((p.name, p.stat().st_mtime_ns)
                       for p in adr_dir_.glob("*.md"))) if adr_dir_.exists() else ()
    key = (str(Path(root).resolve()), sig)
    if key in _ADR_STATUS_CACHE:
        return _ADR_STATUS_CACHE[key]
    from .compiler import parse_frontmatter
    out = set()
    adr_dir = Path(root) / "adr"
    if adr_dir.exists():
        for p in sorted(adr_dir.glob("*.md")):
            try:
                fm, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if str(fm.get("status", "")).lower() == "superseded" and fm.get("id"):
                out.add(str(fm["id"]))
            for s in fm.get("supersedes", []) or []:
                out.add(str(s))
    _ADR_STATUS_CACHE[key] = out
    return out


def _guidance_candidates(root, entry, superseded: set, dropped=None,
                         loaded_adr_files=None, missing_refs=None,
                         superseded_out=None) -> list:
    """The ONE place guidance refs become context candidates (E6).

    Both the resolver (what gets injected) and the backlog estimate (what a
    slice will cost) read this, so they apply the same supersession
    filtering, anchor extraction and per-entry dedup, and cannot disagree.

    Planned entries contribute every ref; built entries only the sections
    NOT listed in `supersedes_guidance` (the shadow replaces the rest). Refs
    into superseded ADRs are skipped and reported in `dropped`. A ref whose
    anchor is not found in the file falls back to the WHOLE file — reported
    in `dropped` as `anchor-missing`, with its full cost, never silently.

    Args:
        root: Substrate root.
        entry: Registry entry.
        superseded: The entry's own `supersedes_guidance` set.
        dropped: Optional list collecting `{kind, ids, reason}` diagnostics.
        loaded_adr_files: Optional set collecting ADR file paths that made
            it in — decision rows authored by those ADRs join the decisions
            block.
        missing_refs: Optional list; when given, a ref to a missing file is
            appended there instead of raising (the estimate reports, the
            resolver fails closed).
        superseded_out: Optional list collecting the refs skipped as
            superseded (either by the entry or by ADR status).

    Returns:
        Candidates `{ref, key, block, anchor_missing}` in ref order, one per
        distinct `(file, anchor)` key. `block` is the rendered injection.
    """
    out, seen = [], set()
    out_of_force = _adr_superseded_ids(root)
    for ref in entry.get("guidance_refs", []):
        if entry.get("status") == "built" and _ref_superseded(ref, superseded):
            if superseded_out is not None:
                superseded_out.append(ref)
            continue
        m = re.search(r"adr/(\d+)", ref)
        if m and (m.group(1) in out_of_force or
                  m.group(1).lstrip("0") in out_of_force):
            if dropped is not None:
                dropped.append({"kind": "guidance-superseded", "ids": [ref],
                                "reason": f"ADR {m.group(1)} is superseded"})
            if superseded_out is not None:
                superseded_out.append(ref)
            continue
        file = ref.split("#")[0]
        anchor = ref.split("#")[1] if "#" in ref else None
        key = (file, anchor)
        if key in seen:
            continue                      # the same section twice is one section
        seen.add(key)
        path = Path(root) / file
        if not path.exists():
            if missing_refs is not None:
                missing_refs.append(ref)
                continue
            from . import SubstrateMissing
            raise SubstrateMissing(
                f"registry {entry['id']!r}: guidance_ref {ref!r} points at a "
                f"missing file — authored substrate is incomplete (fail closed)")
        if loaded_adr_files is not None:
            loaded_adr_files.add(file)
        text = path.read_text(encoding="utf-8")
        anchor_missing = False
        if anchor:
            section = _extract_section(text, anchor)
            if section:
                text = section
            else:
                anchor_missing = True
                if dropped is not None:
                    dropped.append({
                        "kind": "anchor-missing", "ids": [ref],
                        "reason": f"anchor #{anchor} not found in {file}; the "
                                  f"whole file is loaded instead (fallback, "
                                  f"full cost) — fix the ref or the anchor"})
        out.append({"ref": ref, "key": key, "anchor_missing": anchor_missing,
                    "block": f"=== guidance {ref} ({_adr_id(ref)}) ===\n"
                             f"{text.strip()}"})
    return out


def _ref_superseded(ref: str, superseded: set) -> bool:
    for s in superseded:
        # 'adr/007#s2,s3' covers 'adr/007-telemetry.md#s2' and '#s3'
        base = s.split("#")[0]
        anchors = s.split("#")[1].split(",") if "#" in s else []
        if ref.split("#")[0].startswith(base) or base in ref:
            ref_anchor = ref.split("#")[1] if "#" in ref else None
            if not anchors or (ref_anchor and ref_anchor in anchors):
                return True
    return False


def _extract_section(text: str, anchor: str):
    """Sections marked '<!-- #s2 -->' or headers '## s2 ...'."""
    pat = re.compile(
        rf"(?:<!--\s*#{re.escape(anchor)}\s*-->|^#+\s*{re.escape(anchor)}\b)(.*?)"
        rf"(?=<!--\s*#|\n#+\s|\Z)", re.S | re.M)
    m = pat.search(text)
    return m.group(1).strip() if m else None


def block_hash(text: str) -> str:
    """Stable hash of one emitted block; the sidecar keeps one per session."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _open_findings(root, slice_id: str) -> list:
    """Findings parked for this slice that still wait for a human."""
    return [row["finding"]
            for row in read_jsonl(harness_dir(root) / "parked.jsonl")
            if row.get("slice") == slice_id and isinstance(row.get("finding"), dict)]


def _cited_decisions(root, sl: dict, registry: dict) -> list:
    """Decision rows the slice cites: rows whose domain is a declared dep's
    id, kind or domain, plus rows authored by an in-force ADR that a
    declared dep's guidance names. A slice with no deps cites every row."""
    deps = [registry[d] for d in dict.fromkeys(sl.get("declares_dep", []))
            if d in registry]
    keys = set()
    for e in deps:
        keys.update(v for v in (e["id"], e.get("kind", "other"), e.get("domain")) if v)
    out_of_force = _adr_superseded_ids(root)
    adr_files = set()
    for e in deps:
        for ref in e.get("guidance_refs", []):
            m = re.search(r"adr/(\d+)", ref)
            if m and (m.group(1) in out_of_force
                      or m.group(1).lstrip("0") in out_of_force):
                continue
            adr_files.add(ref.split("#")[0])
    rows = []
    for d in sorted(load_decisions(root), key=lambda r: r.get("id", "")):
        from_adr = (d.get("adr_ref") or "").split("#")[0] in adr_files
        if not keys or d.get("domain") in keys or from_adr:
            rows.append(d)
    return rows


def build_blocks(root, sl: dict, config: dict) -> list:
    """The slice's context blocks in priority order. Empty blocks are left
    out; declared ids absent from the registry are ignored here (`resolve`
    fails closed on them)."""
    registry = {e["id"]: e for e in load_registry(root)}
    blocks = []

    def add(key, title, lines):
        if lines:
            blocks.append({"key": key, "priority": BLOCK_PRIORITY[key],
                           "text": f"=== {title} ===\n" + "\n".join(lines)})

    add("findings", "open findings",
        [f"[{f.get('code')} {f.get('rule_ref')}] {f.get('message')}"
         + (f"\n  Fix: {f['fix']}" if f.get("fix") else "")
         + "".join(f"\n{line}" for line in f.get("inject") or [])
         for f in _open_findings(root, sl["id"])])
    add("decisions", "decisions in scope",
        [f"{d['id']} [{d.get('domain')}] {d.get('question')} -> {d.get('answer')}"
         for d in _cited_decisions(root, sl, registry)])
    add("non-goals", "non-goals",
        [f"{b.get('id')} [{b.get('rule_ref')}] {b.get('text')} "
         f"({', '.join(b.get('patterns', []))})"
         for b in load_boundaries(root)])
    add("slice", f"slice {sl['id']}", [
        f"goal: {sl.get('title') or sl['id']}",
        f"statements: {', '.join(sl.get('verifies', [])) or 'none'}",
        f"predicted files: {', '.join(sl.get('predicted_files', [])) or 'none'}"])
    add("modules", MODULES_TITLE,
        [f"{d} ({registry[d].get('status')}, "
         f"{registry[d].get('source') or 'no source'}): "
         f"harness resolve --module {d}"
         for d in dict.fromkeys(sl.get("declares_dep", [])) if d in registry])
    return blocks


def cut_pointer(key: str, slice_id: str) -> str:
    """The one line that replaces a cut block."""
    return (f"[harness: the {key} block was cut to fit {MAX_INJECTION_CHARS} "
            f"characters. Run: harness resolve --slice {slice_id}]")


def fit_blocks(blocks: list, slice_id: str, cap=MAX_INJECTION_CHARS) -> tuple:
    """`(injections, cut)`: one injection per block, in block order; blocks
    are cut lowest priority first until the joined text fits `cap`.
    `cap=None` cuts nothing."""
    cut: list = []

    def render():
        return [cut_pointer(b["key"], slice_id) if b["key"] in cut else b["text"]
                for b in blocks]

    if cap is not None:
        for block in sorted(blocks, key=lambda b: -b["priority"]):
            if len(BLOCK_SEPARATOR.join(render())) <= cap:
                break
            cut.append(block["key"])
    return render(), cut


def resolve(root, slice_id: str, config: dict, *, cap=MAX_INJECTION_CHARS) -> dict:
    """The slice's context: every block, what fits the cap, and what was cut.

    Raises:
        SubstrateMissing: a declared dependency is not in the registry.
    """
    sl = get_slice(root, slice_id)
    known = {e["id"] for e in load_registry(root)}
    for d in sl.get("declares_dep", []):
        if d not in known:
            raise SubstrateMissing(
                f"slice {slice_id}: declares_dep {d!r} not in registry (fail closed)")
    blocks = build_blocks(root, sl, config)
    injections, cut = fit_blocks(blocks, slice_id, cap)
    return {"slice": slice_id, "blocks": blocks, "injections": injections,
            "cut": cut, "chars": len(BLOCK_SEPARATOR.join(injections)),
            "demand_chars": len(BLOCK_SEPARATOR.join(b["text"] for b in blocks))}


def over_cap_finding(slice_id: str, cut: list, demand_chars: int) -> dict:
    """Advisory CONTEXT_OVER_CAP: the slice's context did not fit."""
    from .events import make_finding
    return make_finding(
        "CONTEXT_OVER_CAP", "resolver:cap",
        f"Slice {slice_id} context is {demand_chars} characters, over the "
        f"{MAX_INJECTION_CHARS} cap; cut: {', '.join(cut)}.",
        severity="advisory", key=f"{slice_id}|{','.join(cut)}",
        fix=f"Split slice {slice_id}, or shorten its cited decision rows.")


def render_module(root, module_id: str, config: dict) -> dict:
    """Full context for one registry module: its shadow (built entries) and
    its in-force guidance sections. No cap.

    Raises:
        SubstrateMissing: unknown module id, or a guidance ref names a
            missing file.
    """
    entry = next((e for e in load_registry(root) if e["id"] == module_id), None)
    if entry is None:
        raise SubstrateMissing(
            f"registry has no module {module_id!r}. "
            f"Run: harness resolve --slice <id> to list the slice's modules")
    parts, dropped = [], []
    if entry.get("status") == "built" and entry.get("source"):
        from .extractor.engine import shadow_for
        shadow = shadow_for(root, Path(root) / entry["source"], config)
        if shadow is not None:
            parts.append(render_shadow(shadow, with_docs=True))
    superseded = set(entry.get("supersedes_guidance", []))
    for c in _guidance_candidates(root, entry, superseded, dropped=dropped):
        parts.append(c["block"])
    return {"module": module_id, "text": BLOCK_SEPARATOR.join(parts),
            "dropped": dropped}
