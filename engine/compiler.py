"""Stage-4 transform (`harness compile`): authored artifacts -> enforcement
substrate. ADR frontmatter -> decision rows; abstraction mentions -> registry
skeleton (all planned); API surface -> contract stubs; [non-goal]s -> G3
scope boundaries. Prose is for extrapolation; compiled form is what gates read.

Rows and abstractions may also be authored in the working document's typed
fenced tables (ADR-002 row D-013, parsed in `docsections`); one id may be
claimed by exactly one source.

Boundaries are fully derived: compile REGENERATES boundaries.jsonl from its
sources on every run (same-source-same-output). Decisions and registry merge,
because adjudicated rows and built statuses must survive recompiles.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from . import (HarnessError, SubstrateMissing, harness_dir, load_config,
               now_iso, read_jsonl, write_jsonl)
from .docsections import EPOCH_PREFIX as _EPOCH_PREFIX
from .docsections import (doc_ref_for, merge_doc_blocks,  # noqa: F401
                          parse_doc_blocks, seed_doc_from_spec)
from .registry import registry_kinds

_CODE_SPAN = re.compile(r"`[^`]*`")
PLACEHOLDER_SENTINEL = "EDIT ME"


def _config(root) -> dict:
    """The repo's engine config, or {} outside an initialised repo.

    Only a MISSING config is tolerated: a malformed one must fail loud
    rather than silently compile against engine defaults.
    """
    try:
        return load_config(root)
    except SubstrateMissing:
        return {}


def parse_frontmatter(text: str) -> tuple:
    """Returns (frontmatter_dict, body). Fail loud on malformed frontmatter."""
    if not text.startswith("---"):
        return {}, text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        raise HarnessError("malformed frontmatter: opening '---' without closing")
    try:
        import yaml
        fm = yaml.safe_load(m.group(1)) or {}
    except Exception as exc:
        raise HarnessError(f"frontmatter is not valid YAML: {exc}") from exc
    if not isinstance(fm, dict):
        raise HarnessError("frontmatter must be a mapping")
    return fm, m.group(2)


def _adr_files(root) -> list:
    """Numbered ADRs; *template* files are examples, never compiled."""
    adr_dir = Path(root) / "adr"
    if not adr_dir.exists():
        return []
    return sorted(p for p in adr_dir.glob("*.md")
                  if re.match(r"\d+", p.name) and "template" not in p.name.lower())


def extract_non_goals(text: str) -> list:
    """Paragraph-scoped [non-goal] blocks.

    - A token inside a backtick code span is prose, not a directive.
    - The block runs from the token to the next [non-goal] token or the end
      of the paragraph (multi-line blocks keep their trailing glob lines).
    - ENFORCEMENT INTENT MUST BE EXPLICIT (field report #2-recurrence):
      a backticked path becomes a blocking glob only if it contains a
      wildcard, or is marked `forbid:` — descriptive prose that merely NAMES
      a path ("wiring lives in `infra/x.yaml`") must never hard-block the
      file's own legitimate creation.
    Returns (text, patterns, descriptive_paths) triples.
    """
    results = []
    for para in re.split(r"\n\s*\n", text):
        spans = [(m.start(), m.end()) for m in _CODE_SPAN.finditer(para)]
        tokens = [m for m in re.finditer(r"\[non-goal\]", para)
                  if not any(s <= m.start() < e for s, e in spans)]
        for i, m in enumerate(tokens):
            end = tokens[i + 1].start() if i + 1 < len(tokens) else len(para)
            raw = para[m.end():end]
            block = re.sub(r"\s+", " ", raw).strip()
            if not block:
                continue
            forbid_marked = set(re.findall(r"forbid:\s*`([^`]+)`", raw))
            patterns, descriptive = [], []
            for p in re.findall(r"`([^`]+)`", raw):
                if not any(c in p for c in "*/."):
                    continue  # not path-like
                if "*" in p or p in forbid_marked:
                    if p not in patterns:
                        patterns.append(p)
                elif p not in descriptive:
                    descriptive.append(p)
            results.append((block, patterns, descriptive))
    return results


def _boundary(text: str, patterns: list, source: str, rule_ref: str) -> dict:
    bid = "B-" + hashlib.sha1(text.encode()).hexdigest()[:8]
    return {"id": bid, "source_adr": source, "rule_ref": rule_ref,
            "text": text, "patterns": patterns}


def _out_of_force(root) -> set:
    """ADR ids that no longer bind: status superseded, or named in another
    ADR's supersedes list."""
    out = set()
    for adr in _adr_files(root):
        try:
            fm, _ = parse_frontmatter(adr.read_text(encoding="utf-8"))
        except HarnessError:
            continue
        if str(fm.get("status", "")).lower() == "superseded" and fm.get("id"):
            out.add(str(fm["id"]))
        for s in fm.get("supersedes", []) or []:
            out.add(str(s))
    return out


def compile_substrate(root, working_doc=None, config=None) -> dict:
    """Idempotent: recompiling the same sources produces the same substrate.
    Planned registry entries are RECONCILED against the ADRs currently in
    force — kind/domain/guidance_refs are rebuilt, not appended, so a
    superseded ADR's refs never linger (field report #14/#15).

    `config` (loaded from the repo when omitted) supplies
    `registry.kinds_extra`, the repo's own abstraction kinds."""
    root = Path(root)
    kinds = registry_kinds(config if config is not None else _config(root))
    decisions = {d["id"]: d for d in read_jsonl(harness_dir(root) / "decisions.jsonl")}
    registry = {e["id"]: e for e in read_jsonl(harness_dir(root) / "registry.jsonl")}
    boundaries: dict = {}  # regenerated from scratch: derived files never accumulate
    report = {"decisions": [], "registry": [], "boundaries": [], "contracts": [],
              "contract_gaps": [], "pruned": [], "warnings": [], "adrs": [],
              "skipped_superseded": []}
    now = now_iso()
    superseded_adrs = _out_of_force(root)
    # per-compile authored view of each abstraction, rebuilt from in-force ADRs
    authored: dict = {}  # aid -> {"kind":…, "domain":…, "refs":[…]}
    # which ADR claimed each id: a doc row claiming it too is a hard error
    adr_sources: dict = {"decisions": {}, "abstractions": {}}

    for adr in _adr_files(root):
        fm, body = parse_frontmatter(adr.read_text(encoding="utf-8"))
        if str(fm.get("id", "")) in superseded_adrs or \
                str(fm.get("status", "")).lower() == "superseded":
            report["skipped_superseded"].append(f"adr/{adr.name}")
            continue
        if not fm.get("id"):
            raise HarnessError(f"{adr}: ADR frontmatter missing 'id' (fail closed)")
        adr_id = str(fm["id"])
        adr_ref = f"adr/{adr.name}"
        report["adrs"].append(adr_ref)

        # frontmatter decision_table_rows -> decisions.jsonl
        for row in fm.get("decision_table_rows", []) or []:
            for req in ("id", "domain", "question", "answer"):
                if not row.get(req):
                    raise HarnessError(f"{adr}: decision row missing {req!r}: {row}")
            rid = row["id"]
            adr_sources["decisions"][rid] = adr_ref
            existing = decisions.get(rid)
            if existing and existing.get("origin") == "adjudication":
                continue  # adjudicated rows outrank recompiled phase0 rows
            changed = existing is not None and any(
                existing.get(k) != row[k] for k in ("domain", "question", "answer"))
            created = existing.get("created") if existing else now
            if not created or str(created).startswith(_EPOCH_PREFIX):
                created = now  # never propagate the scaffold placeholder epoch
            new_row = {
                "id": rid, "domain": row["domain"], "question": row["question"],
                "answer": row["answer"], "adr_ref": adr_ref, "origin": "phase0",
                "created": created,
            }
            if row.get("security"):
                # ADR-001: security-marked rows make their slices require an
                # independent forked review before close — must survive compile
                new_row["security"] = True
            if changed:
                new_row["updated"] = now
            decisions[rid] = new_row
            report["decisions"].append(rid)

        # abstraction mentions -> registry skeleton (all planned)
        for ab in fm.get("abstractions", []) or []:
            if isinstance(ab, str):
                ab = {"id": ab, "kind": "other"}
            aid = ab.get("id")
            if not aid:
                raise HarnessError(f"{adr}: abstraction without id: {ab}")
            adr_sources["abstractions"][aid] = adr_ref
            requested_kind = ab.get("kind", "other")
            kind = requested_kind
            if kind not in kinds:
                report["warnings"].append(
                    f"{adr_ref}: abstraction {aid!r} kind {requested_kind!r} is "
                    f"not in the registry enum {sorted(kinds)}; coerced "
                    f"to 'other' but preserved as domain {requested_kind!r} for "
                    f"decision-row matching and author-gate coverage")
                kind = "other"
            auth = authored.setdefault(aid, {"kind": kind,
                                             "domain": requested_kind,
                                             "refs": []})
            auth["kind"], auth["domain"] = kind, requested_kind
            ref = adr_ref_sec(adr_ref, ab)
            if ref not in auth["refs"]:
                auth["refs"].append(ref)
            if aid in registry:
                entry = registry[aid]
                # planned entries adopt authored fields from the ADR — a
                # scaffolded seed with source: null would otherwise silently
                # never qualify for the planned->built flip at close-slice
                if entry.get("status") == "planned":
                    if ab.get("source") and not entry.get("source"):
                        entry["source"] = ab["source"]
                    if ab.get("manifest") and not entry.get("manifest"):
                        entry["manifest"] = ab["manifest"]
                    if ab.get("supersedes_guidance") and not entry.get("supersedes_guidance"):
                        entry["supersedes_guidance"] = ab["supersedes_guidance"]
            else:
                registry[aid] = {
                    "id": aid, "kind": kind, "domain": requested_kind,
                    "status": "planned",
                    "module_id": None, "source": ab.get("source"),
                    "source_hash": None, "shadow": None,
                    "guidance_refs": [ref],
                    "supersedes_guidance": ab.get("supersedes_guidance", []),
                    "manifest": ab.get("manifest", []),
                    "signature_digest": None,
                }
                report["registry"].append(aid)
            # an abstraction may declare it replaces scaffolded/merged entries
            for rid in ab.get("replaces", []) or []:
                victim = registry.get(rid)
                if victim is None or rid == aid:
                    continue
                if victim.get("status") == "built" or victim.get("source"):
                    report["warnings"].append(
                        f"{adr_ref}: {aid!r} replaces {rid!r}, but {rid!r} is "
                        f"built/sourced — not pruned; migrate it explicitly")
                    continue
                del registry[rid]
                report["pruned"].append(rid)

        # [non-goal] blocks -> G3 scope boundaries (ADRs are authoritative;
        # first writer wins on identical text)
        for text_block, patterns, descriptive in extract_non_goals(body):
            b = _boundary(text_block, patterns, adr_id, f"adr:{adr_id}")
            boundaries.setdefault(b["id"], b)
            report["boundaries"].append(b["id"])
            if descriptive:
                report["warnings"].append(
                    f"{adr_ref}: non-goal {b['id']} names concrete path(s) "
                    f"{descriptive} descriptively — NOT enforced; write "
                    f"forbid: `path` (or a glob) to block edits there")
            if not patterns and not descriptive:
                report["warnings"].append(
                    f"{adr_ref}: non-goal {b['id']} has no backticked path/glob — "
                    f"it documents intent but G3 cannot enforce it")

        # API surface -> contract stubs (new contracts only; existing
        # contracts are authored — report gaps instead of rewriting them).
        # contract_mode: generated declares the contract is produced by the
        # build (code-first); compile then owns neither stubs nor gaps (#16).
        surface = fm.get("api_surface", []) or []
        if surface and str(fm.get("contract_mode", "")).lower() == "generated":
            report["warnings"].append(
                f"{adr_ref}: contract_mode=generated — api_surface is "
                f"informational; coverage is the build's responsibility, not "
                f"author-gate's")
            surface = []
        if surface:
            cdir = root / "contracts"
            cdir.mkdir(exist_ok=True)
            stub = cdir / f"{fm.get('contract', 'api')}.yaml"
            ops = []
            for op in surface:
                parts = op.split(None, 1)
                if len(parts) == 2:
                    ops.append((parts[0].lower(), parts[1]))
            import yaml
            if not stub.exists():
                paths: dict = {}
                for method, route in ops:
                    paths.setdefault(route, {})[method] = {
                        "summary": f"stub from {adr_ref}",
                        "responses": {"200": {"description": "ok"}}}
                stub.write_text(yaml.safe_dump({
                    "openapi": "3.0.3",
                    "info": {"title": "generated stub", "version": "0.1.0"},
                    "paths": paths}, sort_keys=True), encoding="utf-8")
                report["contracts"].append(str(stub.relative_to(root)))
            else:
                doc = yaml.safe_load(stub.read_text()) or {}
                have = doc.get("paths") or {}
                for method, route in ops:
                    if route not in have or method not in (have.get(route) or {}):
                        gap = (f"{stub.relative_to(root)}: api_surface op "
                               f"'{method.upper()} {route}' ({adr_ref}) is not in "
                               f"the contract")
                        report["contract_gaps"].append(gap)
                        report["warnings"].append(gap)

    # typed fenced tables in the working document (ADR-002 D-013) are a
    # second authoring surface for the SAME rows — merged before reconcile
    # so doc-declared abstractions get the same guidance-ref treatment
    doc_text = None
    if working_doc:
        doc_ref = doc_ref_for(root, working_doc)
        doc_text = Path(working_doc).read_text(encoding="utf-8")
        merge_doc_blocks(parse_doc_blocks(doc_text, source=doc_ref), doc_ref,
                         decisions=decisions, registry=registry,
                         authored=authored, report=report, now=now,
                         adr_sources=adr_sources, kinds=kinds)

    # reconcile planned entries against the ADRs currently in force:
    # kind/domain/guidance_refs are REPLACED, so superseded or no-longer-
    # declaring ADRs drop off instead of lingering (field report #14)
    for aid, auth in authored.items():
        entry = registry.get(aid)
        if entry is None or entry.get("status") != "planned":
            continue
        if entry.get("guidance_refs") != auth["refs"]:
            entry["guidance_refs"] = auth["refs"]
        entry["kind"] = auth["kind"]
        entry["domain"] = auth["domain"]
    for aid, entry in registry.items():
        if entry.get("status") == "planned" and aid not in authored and \
                entry.get("guidance_refs"):
            stale = [r for r in entry["guidance_refs"]
                     if any(f"adr/{s}" in r or re.search(rf"adr/0*{re.escape(s)}\b", r)
                            for s in superseded_adrs)]
            if stale:
                entry["guidance_refs"] = [r for r in entry["guidance_refs"]
                                          if r not in stale]
                report["warnings"].append(
                    f"registry {aid!r}: dropped guidance_refs into superseded "
                    f"ADRs: {stale}")

    if doc_text is not None:
        for text_block, patterns, descriptive in extract_non_goals(doc_text):
            b = _boundary(text_block, patterns, "working-doc", "adr:phase0")
            if b["id"] in boundaries:
                continue  # same rule already compiled from an ADR: ADR provenance wins
            boundaries[b["id"]] = b
            report["boundaries"].append(b["id"])
            if descriptive:
                report["warnings"].append(
                    f"working-doc: non-goal {b['id']} names concrete path(s) "
                    f"{descriptive} descriptively — NOT enforced; use forbid: "
                    f"`path` or a glob")
            if not patterns and not descriptive:
                report["warnings"].append(
                    f"working-doc: non-goal {b['id']} has no backticked path/glob — "
                    f"G3 cannot enforce it")

    write_jsonl(harness_dir(root) / "decisions.jsonl",
                sorted(decisions.values(), key=lambda d: d["id"]))
    write_jsonl(harness_dir(root) / "registry.jsonl",
                sorted(registry.values(), key=lambda e: e["id"]))
    write_jsonl(harness_dir(root) / "boundaries.jsonl",
                sorted(boundaries.values(), key=lambda b: b["id"]))
    return report


def adr_ref_sec(adr_ref: str, ab: dict) -> str:
    sec = ab.get("section") if isinstance(ab, dict) else None
    return f"{adr_ref}#{sec}" if sec else adr_ref


def _unresolved_open_questions(body: str) -> list:
    """[open-question] lines that carry no resolution marker.

    Resolution markers (any one suffices): the token struck through with
    ~~...~~, the word 'resolved' anywhere on the line ([resolved: adr/NNN],
    '-> resolved', '→ resolved: ...'), or 'deferred:' with an owner. Tokens
    inside backtick code spans are prose, never open questions.
    """
    out = []
    for line in body.splitlines():
        clean = _CODE_SPAN.sub(" ", line)
        if "[open-question]" not in clean:
            continue
        if re.search(r"~~[^~]*\[open-question\][^~]*~~", clean):
            continue  # struck through = resolved
        low = clean.lower()
        # \b keeps 'unresolved' from matching — substring matching is the
        # exact false-positive class this function exists to kill
        if re.search(r"\bresolved\b", low) or "deferred:" in low:
            continue
        m = re.search(r"\[open-question\]\s*(.*)", clean)
        out.append((m.group(1) or clean).strip()[:100])
    return out


def author_gate(root, working_doc=None) -> dict:
    """Day-0 completeness check — blocks backlog generation until it passes.
    The human signs here: the one deliberate checkpoint. Placeholder
    sentinels and epoch timestamps are hard gaps: a scaffold row must never
    compile/build as if ratified (the md-file-bug class)."""
    root = Path(root)
    gaps = []
    decisions = read_jsonl(harness_dir(root) / "decisions.jsonl")
    registry = read_jsonl(harness_dir(root) / "registry.jsonl")
    registry_ids = {e.get("id") for e in registry}

    # every sliceable domain has >=1 decision row. Coverage keys on the
    # entry's DOMAIN (preserved even when kind coerces to 'other'), so
    # custom domains like 'observability' are no longer silently exempt
    # (field report #17). Only a literal kind/domain of 'other' is exempt.
    domains_with_rows = {d.get("domain") for d in decisions}
    for e in registry:
        domain_key = e.get("domain") or e.get("kind")
        if domain_key == "other":
            continue
        if domain_key not in domains_with_rows and \
                e.get("id") not in domains_with_rows:
            gaps.append(f"domain {domain_key!r} (registry entry {e['id']!r}) "
                        f"has no decision row")

    # placeholder sentinels and epoch timestamps never pass the human gate
    for d in decisions:
        blob = f"{d.get('question', '')} {d.get('answer', '')}"
        if PLACEHOLDER_SENTINEL in blob:
            gaps.append(f"decision {d.get('id')!r} still contains the scaffold "
                        f"'{PLACEHOLDER_SENTINEL}' placeholder")
        if str(d.get("created", "")).startswith(_EPOCH_PREFIX):
            gaps.append(f"decision {d.get('id')!r} carries the placeholder epoch "
                        f"timestamp — edit it and re-run compile")
    for e in registry:
        if PLACEHOLDER_SENTINEL in str(e):
            gaps.append(f"registry entry {e.get('id')!r} still contains "
                        f"'{PLACEHOLDER_SENTINEL}'")

    # backlog placeholders + dangling declares_dep
    backlog_path = harness_dir(root) / "backlog.jsonl"
    if backlog_path.exists():
        for s in read_jsonl(backlog_path):
            if PLACEHOLDER_SENTINEL in str(s):
                gaps.append(f"backlog slice {s.get('id')!r} still contains "
                            f"'{PLACEHOLDER_SENTINEL}' — edit or delete the "
                            f"scaffold slice")
            for dep in s.get("declares_dep", []):
                if dep not in registry_ids:
                    gaps.append(f"backlog slice {s.get('id')!r} declares dep "
                                f"{dep!r} which is not in the registry")

    # every open question resolved or deferred-with-owner
    if working_doc:
        doc = Path(working_doc)
        if not doc.exists():
            gaps.append(f"working document {working_doc!r} does not exist")
        else:
            for q in _unresolved_open_questions(doc.read_text(encoding="utf-8")):
                gaps.append(f"open question unresolved and not deferred-with-owner: {q}")

    # contracts lint + api_surface coverage
    cdir = root / "contracts"
    contract_paths: dict = {}
    if cdir.exists():
        import yaml
        for c in sorted(cdir.glob("*.yaml")):
            try:
                doc = yaml.safe_load(c.read_text())
                if not isinstance(doc, dict) or "paths" not in doc:
                    gaps.append(f"{c.relative_to(root)}: not a valid OpenAPI doc "
                                f"(missing 'paths')")
                else:
                    contract_paths[c.stem] = doc.get("paths") or {}
            except Exception as exc:
                gaps.append(f"{c.relative_to(root)}: YAML parse error: {exc}")
    in_force = _out_of_force(root)
    for adr in _adr_files(root):
        fm, _body = parse_frontmatter(adr.read_text(encoding="utf-8"))
        if str(fm.get("id", "")) in in_force or \
                str(fm.get("status", "")).lower() == "superseded":
            continue  # superseded ADRs impose no coverage obligations
        if str(fm.get("contract_mode", "")).lower() == "generated":
            continue  # code-generated contract: coverage is the build's job (#16)
        for op in fm.get("api_surface", []) or []:
            parts = op.split(None, 1)
            if len(parts) != 2:
                continue
            method, route = parts[0].lower(), parts[1]
            covered = any(route in paths and method in (paths.get(route) or {})
                          for paths in contract_paths.values())
            if not covered:
                gaps.append(f"api_surface op '{op}' (adr/{adr.name}) is not "
                            f"covered by any contract in contracts/")

    # registry closure covers guidance refs
    for e in registry:
        for ref in e.get("guidance_refs", []):
            if not (root / ref.split("#")[0]).exists():
                gaps.append(f"registry {e['id']!r}: guidance_ref {ref!r} points at "
                            f"a missing file")

    return {"passed": not gaps, "gaps": gaps}
