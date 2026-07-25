"""C5 — Resolver: slice -> assembled, ranked, token-budgeted context.

Deterministic: same slice + same substrate -> byte-identical output.
Budget is never exceeded. Degradation order: drop docstrings before
dropping modules — a signature without docs beats absence.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import (get_slice, harness_dir, load_decisions, read_jsonl,
               token_estimate)
from .registry import load_registry

RANK_DIRECT, RANK_ONEHOP, RANK_MEMORY = 0, 1, 2


def _adr_id(ref: str) -> str:
    """'adr/007-telemetry.md#s2' -> 'adr:007'."""
    m = re.search(r"adr/(\d+)", ref)
    return f"adr:{m.group(1)}" if m else f"adr:{ref}"


def _load_shadow(root, entry):
    """Fail closed: a built entry whose shadow is missing is the md-file-bug
    class — never a silent omission from Phase-1 context."""
    if not entry.get("shadow"):
        if entry.get("status") == "built":
            from . import SubstrateMissing
            raise SubstrateMissing(
                f"registry {entry['id']!r} is built but has no shadow path; "
                f"run `harness extract {entry.get('source')}`")
        return None
    sp = Path(root) / entry["shadow"]
    if not sp.exists():
        if entry.get("status") == "built":
            from . import SubstrateMissing
            raise SubstrateMissing(
                f"registry {entry['id']!r}: shadow {entry['shadow']!r} missing "
                f"(derived artifact deleted?); run `harness extract --all`")
        return None
    return json.loads(sp.read_text())


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


def _render_guidance(root, entry, superseded: set, dropped=None,
                     loaded_adr_files=None) -> list:
    """Guidance refs for planned entries; for built entries only the sections
    NOT listed in supersedes_guidance survive (the shadow replaces the rest).
    Refs into superseded ADRs are skipped and reported in `dropped`.
    `loaded_adr_files` collects the ADR file paths that made it in — decision
    rows authored by those ADRs join the curated decisions block."""
    blocks = []
    out_of_force = _adr_superseded_ids(root)
    for ref in entry.get("guidance_refs", []):
        if entry.get("status") == "built" and _ref_superseded(ref, superseded):
            continue
        m = re.search(r"adr/(\d+)", ref)
        if m and (m.group(1) in out_of_force or
                  m.group(1).lstrip("0") in out_of_force):
            if dropped is not None:
                dropped.append({"kind": "guidance-superseded", "ids": [ref],
                                "reason": f"ADR {m.group(1)} is superseded"})
            continue
        if loaded_adr_files is not None:
            loaded_adr_files.add(ref.split("#")[0])
        path = Path(root) / ref.split("#")[0]
        if not path.exists():
            from . import SubstrateMissing
            raise SubstrateMissing(
                f"registry {entry['id']!r}: guidance_ref {ref!r} points at a "
                f"missing file — authored substrate is incomplete (fail closed)")
        text = path.read_text(encoding="utf-8")
        anchor = ref.split("#")[1] if "#" in ref else None
        if anchor:
            section = _extract_section(text, anchor)
            if section:
                text = section
        blocks.append((f"guidance:{ref}",
                       f"=== guidance {ref} ({_adr_id(ref)}) ===\n{text.strip()}"))
    return blocks


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


def _durable_memories(root, module_ids: set) -> list:
    rows = read_jsonl(harness_dir(root) / "memory" / "durable.jsonl")
    out = []
    for r in rows:
        edges = r.get("edges", [])
        linked = {e.get("to", "").split(":", 1)[-1] for e in edges
                  if e.get("type") == "remembers"}
        if linked & module_ids:
            out.append(r)
    return sorted(out, key=lambda r: r.get("id", ""))


def resolve(root, slice_id: str, config: dict) -> dict:
    """Assemble injection blocks + the context_loaded manifest they represent."""
    budget = int(config["resolver"]["budget_tokens"])
    sl = get_slice(root, slice_id)
    registry = {e["id"]: e for e in load_registry(root)}

    # (1) declares_dep closure -> registry entries (missing dep = hard error).
    direct_ids = list(dict.fromkeys(sl.get("declares_dep", [])))
    for d in direct_ids:
        if d not in registry:
            from . import SubstrateMissing
            raise SubstrateMissing(
                f"slice {slice_id}: declares_dep {d!r} not in registry (fail closed)")

    candidates = []  # (rank, sort_key, kind, id, render_full, render_degraded, manifest_ids)
    guidance_dropped = []
    loaded_adr_files: set = set()

    module_ids, domains = set(), set()
    onehop_seen = set(direct_ids)
    for did in sorted(direct_ids):
        entry = registry[did]
        domains.add(entry.get("kind", "other"))
        if entry.get("domain"):
            domains.add(entry["domain"])  # custom domains survive kind coercion (#17)
        superseded = set(entry.get("supersedes_guidance", []))
        shadow = _load_shadow(root, entry) if entry.get("status") == "built" else None
        if shadow is not None:
            module_ids.add(shadow["module_id"])
            module_ids.add(did)
            full = render_shadow(shadow, with_docs=True)
            degraded = render_shadow(shadow, with_docs=False)
            candidates.append((RANK_DIRECT, did, "shadow", f"shadow:{did}",
                               full, degraded, [f"shadow:{did}"]))
            # (5) one-hop type closure from shadow imports (depth-limited to 1)
            for imp in shadow.get("imports", []):
                hop = registry.get(imp)
                if hop is None or hop["id"] in onehop_seen:
                    continue
                onehop_seen.add(hop["id"])
                hop_shadow = _load_shadow(root, hop) if hop.get("status") == "built" else None
                if hop_shadow is not None:
                    candidates.append((RANK_ONEHOP, hop["id"], "shadow",
                                       f"shadow:{hop['id']}",
                                       render_shadow(hop_shadow, True),
                                       render_shadow(hop_shadow, False),
                                       [f"shadow:{hop['id']}"]))
        # (2) guidance refs: planned entries fully; built entries only
        # non-superseded (non-signature-expressible) sections.
        for gid, block in _render_guidance(root, entry, superseded,
                                           dropped=guidance_dropped,
                                           loaded_adr_files=loaded_adr_files):
            candidates.append((RANK_DIRECT, did + "|" + gid, "guidance",
                               _adr_id(gid.split(":", 1)[1]), block, block,
                               [_adr_id(gid.split(":", 1)[1])]))

    # (3) decision rows for domains touched. Domain keys are the declared
    # deps' kinds AND their ids: a row with domain "observability" must reach
    # a slice declaring the "observability" entry even when its registry kind
    # was coerced to "other". Rows authored by an ADR already loaded for this
    # slice ALSO join — the curated decisions block must be a superset of the
    # binding rules the builder can see in that ADR's frontmatter, regardless
    # of how the row's domain was authored (re-audit remaining #1).
    domain_keys = domains | set(direct_ids)
    dec_lines, dec_ids = [], []
    for d in sorted(load_decisions(root), key=lambda r: r.get("id", "")):
        from_loaded_adr = (d.get("adr_ref") or "").split("#")[0] in loaded_adr_files
        if d.get("domain") in domain_keys or from_loaded_adr or not domain_keys:
            dec_lines.append(f"{d['id']} [{d.get('domain')}] {d.get('question')} "
                             f"-> {d.get('answer')}")
            dec_ids.append(f"decision:{d['id']}")
    if dec_lines:
        block = "=== decisions in scope ===\n" + "\n".join(dec_lines)
        candidates.append((RANK_DIRECT, "zz|decisions", "decisions", "decisions",
                           block, block, dec_ids))

    # (4) durable memories edged to these modules, ranked below shadows
    for mem in _durable_memories(root, module_ids | set(direct_ids)):
        block = (f"=== memory {mem['id']} ({mem.get('kind')}) ===\n"
                 f"{mem.get('content', '')}")
        candidates.append((RANK_MEMORY, mem["id"], "memory",
                           f"memory:{mem['id']}", block, block,
                           [f"memory:{mem['id']}"]))

    # (6) rank direct > one-hop > memories; deterministic within rank.
    candidates.sort(key=lambda c: (c[0], c[1]))

    # (7) cut at budget, degrading per config: docstrings first, then modules.
    chosen, manifest, dropped = [], [], []
    used = 0
    degrade_docs = config["resolver"]["degrade"] == "drop_docstrings_before_modules"
    for rank, _key, kind, _cid, full, degraded, ids in candidates:
        cost_full = token_estimate(full)
        if used + cost_full <= budget:
            chosen.append(full)
            used += cost_full
            manifest.extend(ids)
            continue
        cost_deg = token_estimate(degraded)
        if degrade_docs and degraded != full and used + cost_deg <= budget:
            chosen.append(degraded)
            used += cost_deg
            manifest.extend(ids)
            continue
        dropped.append({"kind": kind, "ids": ids, "rank": rank})

    return {
        "slice": slice_id,
        "injections": chosen,
        "context_loaded": list(dict.fromkeys(manifest)),
        "token_estimate": used,
        "budget": budget,
        "dropped": dropped + guidance_dropped,
    }


def context_cost_estimate(root, declares_dep: list, config: dict) -> int:
    """Backlog-time cost: declared deps -> shadow/guidance sizes through the
    resolver's own budget logic (spec §5.6)."""
    registry = {e["id"]: e for e in load_registry(root)}
    total = 0
    for did in declares_dep:
        entry = registry.get(did)
        if entry is None:
            continue
        shadow = _load_shadow(root, entry)
        if entry.get("status") == "built" and shadow is not None:
            total += token_estimate(render_shadow(shadow, True))
        for ref in entry.get("guidance_refs", []):
            p = Path(root) / ref.split("#")[0]
            if p.exists():
                total += token_estimate(p.read_text(encoding="utf-8"))
    return total
